# -*- coding: utf-8 -*-
"""
Web Dashboard Server for SwitchBot/Netatmo Monitoring
Python 3.7+ compatible, uses only standard library.

Provides:
- / : Dashboard HTML page with auto-refresh (30 seconds)
- /api/data : JSON API for sensor data
- /health : Health check endpoint
"""
import json
import logging
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for dashboard endpoints."""

    # Reference to database (set by DashboardServer)
    db = None

    def log_message(self, format, *args):
        """Override to use logging module instead of stderr."""
        logging.debug("Dashboard: %s - %s", self.address_string(), format % args)

    def do_GET(self):
        """Handle GET requests."""
        if self.path == '/':
            self._serve_dashboard()
        elif self.path == '/api/data':
            self._serve_api_data()
        elif self.path == '/health':
            self._serve_health()
        else:
            self.send_error(404, 'Not Found')

    def _serve_health(self):
        """Serve health check endpoint."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = json.dumps({
            'status': 'ok',
            'timestamp': datetime.now().isoformat()
        })
        self.wfile.write(response.encode('utf-8'))

    def _serve_api_data(self):
        """Serve sensor data as JSON."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        data = self._get_sensor_data()
        response = json.dumps(data, ensure_ascii=False, indent=2)
        self.wfile.write(response.encode('utf-8'))

    def _get_sensor_data(self):
        """Get sensor data from database."""
        if self.db is None:
            return {'error': 'Database not available'}

        now = datetime.now()
        result = {
            'timestamp': now.isoformat(),
            'last_updated': None,
            'switchbot': {
                'outdoor': [],
                'indoor': []
            },
            'netatmo': {
                'outdoor': [],
                'indoor': [],
                'wind': [],
                'rain': []
            }
        }

        last_updated = None

        # Get SwitchBot sensor data
        try:
            sensor_devices = self.db.get_all_sensor_devices()
            for device in sensor_devices:
                device_id = device['device_id']
                device_name = device['device_name']

                # Get last 24 hours data
                history = self.db.get_sensor_data_last_24h(device_id)
                if not history:
                    continue

                latest = history[-1] if history else {}

                # Track last updated time
                recorded_at = latest.get('recorded_at')
                if recorded_at:
                    try:
                        ts = datetime.fromisoformat(recorded_at.replace('Z', '+00:00'))
                        if last_updated is None or ts > last_updated:
                            last_updated = ts
                    except (ValueError, TypeError):
                        pass

                device_data = {
                    'device_name': device_name,
                    'latest': {
                        'temperature': latest.get('temperature'),
                        'humidity': latest.get('humidity'),
                        'co2': latest.get('co2'),
                        'light_level': latest.get('light_level'),
                        'recorded_at': recorded_at
                    },
                    'history': history
                }

                # Classify as outdoor or indoor
                if self._is_outdoor_sensor(device_name):
                    result['switchbot']['outdoor'].append(device_data)
                else:
                    result['switchbot']['indoor'].append(device_data)

        except Exception as e:
            logging.error("Error getting SwitchBot data: %s", e)

        # Get Netatmo sensor data
        try:
            netatmo_devices = self.db.get_all_netatmo_devices()
            for device in netatmo_devices:
                device_id = device['device_id']
                device_name = device['device_name']
                module_type = device.get('module_type', '')
                is_outdoor = device.get('is_outdoor', False)

                # Get last 24 hours data
                history = self.db.get_netatmo_data_last_24h(device_id)
                if not history:
                    continue

                latest = history[-1] if history else {}

                # Track last updated time
                recorded_at = latest.get('recorded_at')
                if recorded_at:
                    try:
                        ts = datetime.fromisoformat(recorded_at.replace('Z', '+00:00'))
                        if last_updated is None or ts > last_updated:
                            last_updated = ts
                    except (ValueError, TypeError):
                        pass

                device_data = {
                    'device_name': device_name,
                    'module_type': module_type,
                    'latest': {
                        'temperature': latest.get('temperature'),
                        'humidity': latest.get('humidity'),
                        'co2': latest.get('co2'),
                        'pressure': latest.get('pressure'),
                        'noise': latest.get('noise'),
                        'wind_strength': latest.get('wind_strength'),
                        'wind_angle': latest.get('wind_angle'),
                        'gust_strength': latest.get('gust_strength'),
                        'rain': latest.get('rain'),
                        'rain_1h': latest.get('rain_1h'),
                        'rain_24h': latest.get('rain_24h'),
                        'recorded_at': recorded_at
                    },
                    'history': history
                }

                # Classify by module type
                if module_type == 'NAModule2':
                    result['netatmo']['wind'].append(device_data)
                elif module_type == 'NAModule3':
                    result['netatmo']['rain'].append(device_data)
                elif is_outdoor:
                    result['netatmo']['outdoor'].append(device_data)
                else:
                    result['netatmo']['indoor'].append(device_data)

        except Exception as e:
            logging.error("Error getting Netatmo data: %s", e)

        # Set last updated timestamp
        if last_updated:
            result['last_updated'] = last_updated.isoformat()

        return result

    def _is_outdoor_sensor(self, device_name):
        """Check if device is an outdoor sensor."""
        outdoor_keywords = ['防水温湿度計', '屋外', 'Outdoor', 'outdoor']
        for keyword in outdoor_keywords:
            if keyword in device_name:
                return True
        return False

    def _serve_dashboard(self):
        """Serve dashboard HTML page."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()

        html = self._generate_dashboard_html()
        self.wfile.write(html.encode('utf-8'))

    def _generate_dashboard_html(self):
        """Generate dashboard HTML with embedded data and Chart.js."""
        return '''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SwitchBot/Netatmo Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            padding: 20px;
            min-height: 100vh;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        .header h1 {
            font-size: 1.8em;
            margin-bottom: 10px;
            color: #4fc3f7;
        }
        .header .last-updated {
            color: #888;
            font-size: 0.9em;
        }
        .section {
            margin-bottom: 40px;
        }
        .section h2 {
            font-size: 1.3em;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #333;
            color: #81c784;
        }
        .cards {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .card {
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        }
        .card h3 {
            font-size: 1em;
            margin-bottom: 12px;
            color: #4fc3f7;
        }
        .card .values {
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
        }
        .card .value-item {
            text-align: center;
        }
        .card .value-item .label {
            font-size: 0.75em;
            color: #888;
            margin-bottom: 4px;
        }
        .card .value-item .value {
            font-size: 1.5em;
            font-weight: bold;
        }
        .card .value-item .unit {
            font-size: 0.7em;
            color: #888;
        }
        .temp { color: #ff7043; }
        .humidity { color: #42a5f5; }
        .co2 { color: #ab47bc; }
        .pressure { color: #26a69a; }
        .noise { color: #ffca28; }
        .wind { color: #78909c; }
        .rain { color: #5c6bc0; }
        .light { color: #ffd54f; }
        .chart-container {
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .chart-container h3 {
            font-size: 1em;
            margin-bottom: 15px;
            color: #4fc3f7;
        }
        .chart-wrapper {
            position: relative;
            height: 300px;
        }
        .loading {
            text-align: center;
            padding: 50px;
            color: #888;
        }
        .error {
            text-align: center;
            padding: 20px;
            color: #ef5350;
            background: rgba(239, 83, 80, 0.1);
            border-radius: 8px;
        }
        @media (max-width: 600px) {
            body {
                padding: 10px;
            }
            .cards {
                grid-template-columns: 1fr;
            }
            .chart-wrapper {
                height: 250px;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Environment Dashboard</h1>
        <div class="last-updated" id="lastUpdated">Loading...</div>
    </div>

    <div id="content">
        <div class="loading">Loading sensor data...</div>
    </div>

    <script>
        // Chart.js default configuration
        Chart.defaults.color = '#888';
        Chart.defaults.borderColor = '#333';

        // Fetch data and render dashboard
        async function loadDashboard() {
            try {
                const response = await fetch('/api/data');
                const data = await response.json();
                renderDashboard(data);
            } catch (error) {
                document.getElementById('content').innerHTML =
                    '<div class="error">Error loading data: ' + error.message + '</div>';
            }
        }

        function formatTime(isoString) {
            if (!isoString) return '-';
            const date = new Date(isoString);
            return date.toLocaleString('ja-JP', {
                month: 'numeric',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        }

        function formatValue(value, decimals = 1) {
            if (value === null || value === undefined) return '-';
            return Number(value).toFixed(decimals);
        }

        function formatTimeLabel(isoString) {
            if (!isoString) return '';
            const date = new Date(isoString);
            return date.toLocaleString('ja-JP', {
                hour: '2-digit',
                minute: '2-digit'
            });
        }

        function renderDashboard(data) {
            // Update last updated time
            document.getElementById('lastUpdated').textContent =
                'Last updated: ' + formatTime(data.last_updated);

            let html = '';

            // Outdoor section
            const outdoorDevices = [
                ...data.switchbot.outdoor.map(d => ({...d, source: 'SB'})),
                ...data.netatmo.outdoor.map(d => ({...d, source: 'NA'}))
            ];
            if (outdoorDevices.length > 0) {
                html += renderSection('Outdoor', outdoorDevices, ['temperature', 'humidity']);
            }

            // Indoor section
            const indoorDevices = [
                ...data.switchbot.indoor.map(d => ({...d, source: 'SB'})),
                ...data.netatmo.indoor.map(d => ({...d, source: 'NA'}))
            ];
            if (indoorDevices.length > 0) {
                html += renderSection('Indoor', indoorDevices, ['temperature', 'humidity', 'co2', 'pressure', 'noise']);
            }

            // Wind section
            if (data.netatmo.wind.length > 0) {
                html += renderWindSection(data.netatmo.wind);
            }

            // Rain section
            if (data.netatmo.rain.length > 0) {
                html += renderRainSection(data.netatmo.rain);
            }

            document.getElementById('content').innerHTML = html;

            // Render charts after DOM update
            setTimeout(() => {
                renderCharts(data);
            }, 100);
        }

        function renderSection(title, devices, metrics) {
            let html = '<div class="section">';
            html += '<h2>' + title + '</h2>';
            html += '<div class="cards">';

            for (const device of devices) {
                html += '<div class="card">';
                html += '<h3>[' + device.source + '] ' + device.device_name + '</h3>';
                html += '<div class="values">';

                const latest = device.latest || {};

                if (metrics.includes('temperature') && latest.temperature !== null) {
                    html += renderValueItem('Temp', latest.temperature, '°C', 'temp', 1);
                }
                if (metrics.includes('humidity') && latest.humidity !== null) {
                    html += renderValueItem('Humidity', latest.humidity, '%', 'humidity', 0);
                }
                if (metrics.includes('co2') && latest.co2 !== null && latest.co2 !== undefined) {
                    html += renderValueItem('CO2', latest.co2, 'ppm', 'co2', 0);
                }
                if (metrics.includes('pressure') && latest.pressure !== null && latest.pressure !== undefined) {
                    html += renderValueItem('Pressure', latest.pressure, 'hPa', 'pressure', 1);
                }
                if (metrics.includes('noise') && latest.noise !== null && latest.noise !== undefined) {
                    html += renderValueItem('Noise', latest.noise, 'dB', 'noise', 0);
                }
                if (latest.light_level !== null && latest.light_level !== undefined) {
                    html += renderValueItem('Light', latest.light_level, '', 'light', 0);
                }

                html += '</div></div>';
            }

            html += '</div>';

            // Chart placeholders
            html += '<div class="chart-container"><h3>' + title + ' Temperature</h3>';
            html += '<div class="chart-wrapper"><canvas id="chart-' + title.toLowerCase() + '-temp"></canvas></div></div>';
            html += '<div class="chart-container"><h3>' + title + ' Humidity</h3>';
            html += '<div class="chart-wrapper"><canvas id="chart-' + title.toLowerCase() + '-humidity"></canvas></div></div>';

            if (metrics.includes('co2')) {
                html += '<div class="chart-container"><h3>CO2</h3>';
                html += '<div class="chart-wrapper"><canvas id="chart-' + title.toLowerCase() + '-co2"></canvas></div></div>';
            }
            if (metrics.includes('pressure')) {
                html += '<div class="chart-container"><h3>Pressure</h3>';
                html += '<div class="chart-wrapper"><canvas id="chart-' + title.toLowerCase() + '-pressure"></canvas></div></div>';
            }
            if (metrics.includes('noise')) {
                html += '<div class="chart-container"><h3>Noise</h3>';
                html += '<div class="chart-wrapper"><canvas id="chart-' + title.toLowerCase() + '-noise"></canvas></div></div>';
            }

            html += '</div>';
            return html;
        }

        function renderWindSection(devices) {
            let html = '<div class="section">';
            html += '<h2>Wind</h2>';
            html += '<div class="cards">';

            for (const device of devices) {
                const latest = device.latest || {};
                html += '<div class="card">';
                html += '<h3>[NA] ' + device.device_name + '</h3>';
                html += '<div class="values">';
                if (latest.wind_strength !== null && latest.wind_strength !== undefined) {
                    const windMs = (latest.wind_strength / 3.6).toFixed(1);
                    html += renderValueItem('Wind', windMs, 'm/s', 'wind', 1);
                }
                if (latest.gust_strength !== null && latest.gust_strength !== undefined) {
                    const gustMs = (latest.gust_strength / 3.6).toFixed(1);
                    html += renderValueItem('Gust', gustMs, 'm/s', 'wind', 1);
                }
                if (latest.wind_angle !== null && latest.wind_angle !== undefined) {
                    html += renderValueItem('Dir', latest.wind_angle, '°', 'wind', 0);
                }
                html += '</div></div>';
            }

            html += '</div>';
            html += '<div class="chart-container"><h3>Wind Speed</h3>';
            html += '<div class="chart-wrapper"><canvas id="chart-wind"></canvas></div></div>';
            html += '</div>';
            return html;
        }

        function renderRainSection(devices) {
            let html = '<div class="section">';
            html += '<h2>Rain</h2>';
            html += '<div class="cards">';

            for (const device of devices) {
                const latest = device.latest || {};
                html += '<div class="card">';
                html += '<h3>[NA] ' + device.device_name + '</h3>';
                html += '<div class="values">';
                if (latest.rain !== null && latest.rain !== undefined) {
                    html += renderValueItem('Now', latest.rain, 'mm', 'rain', 1);
                }
                if (latest.rain_1h !== null && latest.rain_1h !== undefined) {
                    html += renderValueItem('1h', latest.rain_1h, 'mm', 'rain', 1);
                }
                if (latest.rain_24h !== null && latest.rain_24h !== undefined) {
                    html += renderValueItem('24h', latest.rain_24h, 'mm', 'rain', 1);
                }
                html += '</div></div>';
            }

            html += '</div>';
            html += '<div class="chart-container"><h3>Rain</h3>';
            html += '<div class="chart-wrapper"><canvas id="chart-rain"></canvas></div></div>';
            html += '</div>';
            return html;
        }

        function renderValueItem(label, value, unit, colorClass, decimals) {
            return '<div class="value-item">' +
                '<div class="label">' + label + '</div>' +
                '<div class="value ' + colorClass + '">' + formatValue(value, decimals) +
                '<span class="unit">' + unit + '</span></div></div>';
        }

        function renderCharts(data) {
            const colors = [
                'rgba(255, 112, 67, 1)',   // orange
                'rgba(66, 165, 245, 1)',   // blue
                'rgba(171, 71, 188, 1)',   // purple
                'rgba(38, 166, 154, 1)',   // teal
                'rgba(255, 202, 40, 1)',   // amber
                'rgba(236, 64, 122, 1)',   // pink
            ];

            // Outdoor charts
            const outdoorDevices = [
                ...data.switchbot.outdoor.map(d => ({...d, source: 'SB'})),
                ...data.netatmo.outdoor.map(d => ({...d, source: 'NA'}))
            ];
            if (outdoorDevices.length > 0) {
                renderLineChart('chart-outdoor-temp', outdoorDevices, 'temperature', colors);
                renderLineChart('chart-outdoor-humidity', outdoorDevices, 'humidity', colors);
            }

            // Indoor charts
            const indoorDevices = [
                ...data.switchbot.indoor.map(d => ({...d, source: 'SB'})),
                ...data.netatmo.indoor.map(d => ({...d, source: 'NA'}))
            ];
            if (indoorDevices.length > 0) {
                renderLineChart('chart-indoor-temp', indoorDevices, 'temperature', colors);
                renderLineChart('chart-indoor-humidity', indoorDevices, 'humidity', colors);
                renderLineChart('chart-indoor-co2', indoorDevices, 'co2', colors);
                renderLineChart('chart-indoor-pressure', indoorDevices, 'pressure', colors);
                renderLineChart('chart-indoor-noise', indoorDevices, 'noise', colors);
            }

            // Wind chart
            if (data.netatmo.wind.length > 0) {
                renderWindChart('chart-wind', data.netatmo.wind);
            }

            // Rain chart
            if (data.netatmo.rain.length > 0) {
                renderRainChart('chart-rain', data.netatmo.rain);
            }
        }

        function renderLineChart(canvasId, devices, metric, colors) {
            if (!document.getElementById(canvasId)) return;

            const datasets = [];

            devices.forEach((device, index) => {
                if (!device.history || device.history.length === 0) return;

                const values = device.history
                    .filter(h => h[metric] !== null && h[metric] !== undefined)
                    .map(h => ({
                        x: new Date(h.recorded_at),
                        y: h[metric]
                    }));

                if (values.length === 0) return;

                datasets.push({
                    label: '[' + device.source + '] ' + device.device_name,
                    data: values,
                    borderColor: colors[index % colors.length],
                    backgroundColor: colors[index % colors.length].replace('1)', '0.1)'),
                    borderWidth: 2,
                    tension: 0.3,
                    pointRadius: 0,
                    fill: false
                });
            });

            if (datasets.length === 0) return;

            createChart(canvasId, {
                type: 'line',
                data: { datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        intersect: false
                    },
                    plugins: {
                        legend: {
                            position: 'top',
                            labels: { boxWidth: 12 }
                        }
                    },
                    scales: {
                        x: {
                            type: 'time',
                            time: {
                                unit: 'hour',
                                displayFormats: { hour: 'HH:mm' }
                            }
                        },
                        y: {
                            beginAtZero: false
                        }
                    }
                }
            });
        }

        function renderWindChart(canvasId, devices) {
            if (!document.getElementById(canvasId)) return;

            const device = devices[0];
            if (!device || !device.history) return;

            const windData = device.history
                .filter(h => h.wind_strength !== null)
                .map(h => ({
                    x: new Date(h.recorded_at),
                    y: h.wind_strength / 3.6  // Convert km/h to m/s
                }));

            const gustData = device.history
                .filter(h => h.gust_strength !== null)
                .map(h => ({
                    x: new Date(h.recorded_at),
                    y: h.gust_strength / 3.6  // Convert km/h to m/s
                }));

            createChart(canvasId, {
                type: 'line',
                data: {
                    datasets: [
                        {
                            label: 'Wind Speed (m/s)',
                            data: windData,
                            borderColor: 'rgba(66, 165, 245, 1)',
                            backgroundColor: 'rgba(66, 165, 245, 0.1)',
                            borderWidth: 2,
                            tension: 0.3,
                            pointRadius: 0,
                            fill: true
                        },
                        {
                            label: 'Gust (m/s)',
                            data: gustData,
                            borderColor: 'rgba(255, 112, 67, 1)',
                            backgroundColor: 'rgba(255, 112, 67, 0.1)',
                            borderWidth: 2,
                            tension: 0.3,
                            pointRadius: 0,
                            fill: false
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'top' }
                    },
                    scales: {
                        x: {
                            type: 'time',
                            time: {
                                unit: 'hour',
                                displayFormats: { hour: 'HH:mm' }
                            }
                        },
                        y: {
                            beginAtZero: true,
                            title: { display: true, text: 'm/s' }
                        }
                    }
                }
            });
        }

        function renderRainChart(canvasId, devices) {
            if (!document.getElementById(canvasId)) return;

            const device = devices[0];
            if (!device || !device.history) return;

            const rain1hData = device.history
                .filter(h => h.rain_1h !== null)
                .map(h => ({
                    x: new Date(h.recorded_at),
                    y: h.rain_1h
                }));

            const rain24hData = device.history
                .filter(h => h.rain_24h !== null)
                .map(h => ({
                    x: new Date(h.recorded_at),
                    y: h.rain_24h
                }));

            createChart(canvasId, {
                type: 'line',
                data: {
                    datasets: [
                        {
                            label: 'Rain 1h (mm)',
                            data: rain1hData,
                            borderColor: 'rgba(92, 107, 192, 1)',
                            backgroundColor: 'rgba(92, 107, 192, 0.3)',
                            borderWidth: 2,
                            tension: 0,
                            pointRadius: 0,
                            fill: true,
                            yAxisID: 'y'
                        },
                        {
                            label: 'Rain 24h (mm)',
                            data: rain24hData,
                            borderColor: 'rgba(38, 166, 154, 1)',
                            backgroundColor: 'rgba(38, 166, 154, 0.1)',
                            borderWidth: 2,
                            tension: 0.3,
                            pointRadius: 0,
                            fill: false,
                            yAxisID: 'y1'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'top' }
                    },
                    scales: {
                        x: {
                            type: 'time',
                            time: {
                                unit: 'hour',
                                displayFormats: { hour: 'HH:mm' }
                            }
                        },
                        y: {
                            type: 'linear',
                            position: 'left',
                            beginAtZero: true,
                            title: { display: true, text: '1h (mm)' }
                        },
                        y1: {
                            type: 'linear',
                            position: 'right',
                            beginAtZero: true,
                            title: { display: true, text: '24h (mm)' },
                            grid: { drawOnChartArea: false }
                        }
                    }
                }
            });
        }

        // Store chart instances for cleanup
        const chartInstances = {};

        function destroyAllCharts() {
            Object.keys(chartInstances).forEach(key => {
                if (chartInstances[key]) {
                    chartInstances[key].destroy();
                    delete chartInstances[key];
                }
            });
        }

        // Override Chart creation to track instances
        function createChart(canvasId, config) {
            const canvas = document.getElementById(canvasId);
            if (!canvas) return null;

            // Destroy existing chart on this canvas
            if (chartInstances[canvasId]) {
                chartInstances[canvasId].destroy();
            }

            const chart = new Chart(canvas, config);
            chartInstances[canvasId] = chart;
            return chart;
        }

        // Load on page ready
        loadDashboard();

        // Auto-refresh every 30 seconds (data only, no page reload)
        setInterval(() => {
            console.log('Refreshing data...');
            loadDashboard();
        }, 30000);
    </script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
</body>
</html>'''


class DashboardServer:
    """HTTP server for the dashboard."""

    def __init__(self, port=7777, db=None):
        """
        Initialize dashboard server.

        Args:
            port: HTTP server port (default: 7777)
            db: DeviceDatabase instance for data access
        """
        self.port = port
        self.db = db
        self.server = None
        self.thread = None
        self._running = False

    def start(self):
        """Start the dashboard server in a background thread."""
        if self._running:
            logging.warning("Dashboard server already running")
            return

        # Set database reference on handler class
        DashboardHandler.db = self.db

        try:
            self.server = HTTPServer(('0.0.0.0', self.port), DashboardHandler)
            self._running = True

            self.thread = threading.Thread(target=self._serve, daemon=True)
            self.thread.start()

            logging.info("Dashboard server started on port %d", self.port)

        except Exception as e:
            logging.error("Failed to start dashboard server: %s", e)
            self._running = False

    def _serve(self):
        """Serve requests until stopped."""
        while self._running:
            try:
                self.server.handle_request()
            except Exception as e:
                if self._running:
                    logging.error("Dashboard server error: %s", e)

    def stop(self):
        """Stop the dashboard server."""
        if not self._running:
            return

        self._running = False

        if self.server:
            try:
                self.server.shutdown()
            except Exception:
                pass

        logging.info("Dashboard server stopped")

    def get_url(self):
        """Get the dashboard URL."""
        return "http://localhost:{}".format(self.port)


if __name__ == '__main__':
    # Standalone test mode
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("Starting dashboard server on port 7777...")
    print("Open http://localhost:7777 in your browser")
    print("Press Ctrl+C to stop")

    server = DashboardServer(port=7777)
    server.start()

    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping server...")
        server.stop()
