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

    # Security device types
    SECURITY_DEVICE_TYPES = [
        'Smart Lock', 'Smart Lock Pro', 'Lock',
        'Contact Sensor', 'Motion Sensor',
        'Keypad', 'Keypad Touch',
        'Video Doorbell'
    ]

    # Track last event ID for polling
    last_event_id = 0

    def do_GET(self):
        """Handle GET requests."""
        if self.path == '/':
            self._serve_dashboard()
        elif self.path == '/api/data':
            self._serve_api_data()
        elif self.path.startswith('/api/events'):
            self._serve_api_events()
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

    def _serve_api_events(self):
        """Serve recent security events for toast notifications."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        # Parse since parameter from query string
        since = None
        if '?' in self.path:
            query = self.path.split('?')[1]
            for param in query.split('&'):
                if param.startswith('since='):
                    since = param.split('=')[1]

        events = self._get_security_events(since)
        response = json.dumps(events, ensure_ascii=False)
        self.wfile.write(response.encode('utf-8'))

    def _get_security_events(self, since=None):
        """Get recent security events from device history."""
        if self.db is None:
            return {'events': []}

        try:
            conn = self.db._get_connection()
            cursor = conn.cursor()

            # Get events from the last hour (or since timestamp)
            if since:
                cursor.execute('''
                    SELECT id, device_id, device_name, device_type, status_json, recorded_at
                    FROM device_history
                    WHERE device_type IN (?, ?, ?, ?, ?, ?, ?, ?)
                    AND recorded_at > ?
                    ORDER BY recorded_at DESC
                    LIMIT 50
                ''', (*self.SECURITY_DEVICE_TYPES, since))
            else:
                cursor.execute('''
                    SELECT id, device_id, device_name, device_type, status_json, recorded_at
                    FROM device_history
                    WHERE device_type IN (?, ?, ?, ?, ?, ?, ?, ?)
                    AND recorded_at >= datetime('now', 'localtime', '-1 hour')
                    ORDER BY recorded_at DESC
                    LIMIT 50
                ''', self.SECURITY_DEVICE_TYPES)

            rows = cursor.fetchall()
            conn.close()

            events = []
            for row in rows:
                status = json.loads(row['status_json']) if row['status_json'] else {}
                event = {
                    'id': row['id'],
                    'device_name': row['device_name'],
                    'device_type': row['device_type'],
                    'status': status,
                    'recorded_at': row['recorded_at'],
                    'message': self._format_security_message(row['device_name'], row['device_type'], status)
                }
                events.append(event)

            return {'events': events}

        except Exception as e:
            logging.error("Error getting security events: %s", e)
            return {'events': [], 'error': str(e)}

    def _format_security_message(self, device_name, device_type, status):
        """Format security event message in Japanese."""
        if 'Lock' in device_type:
            lock_state = status.get('lockState', '').lower()
            if lock_state == 'locked':
                return '🔒 {} が施錠されました'.format(device_name)
            elif lock_state == 'unlocked':
                return '🔓 {} が解錠されました'.format(device_name)
            elif lock_state == 'jammed':
                return '⚠️ {} がジャム状態です'.format(device_name)
        elif device_type == 'Contact Sensor':
            open_state = status.get('openState', '').lower()
            if open_state == 'open':
                return '🚪 {} が開きました'.format(device_name)
            elif open_state in ('close', 'closed'):
                return '🚪 {} が閉まりました'.format(device_name)
        elif device_type == 'Motion Sensor':
            if status.get('moveDetected', False):
                return '👁 {} が動きを検知しました'.format(device_name)
        elif device_type == 'Video Doorbell':
            return '🔔 {} が押されました'.format(device_name)

        return '{} の状態が変化しました'.format(device_name)

    def _get_sensor_data(self):
        """Get sensor data from database."""
        if self.db is None:
            return {'error': 'Database not available'}

        now = datetime.now()
        result = {
            'timestamp': now.isoformat(),
            'last_updated': None,
            'security': [],
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

        # Get security device states (from device_states + latest from device_history)
        try:
            conn = self.db._get_connection()
            cursor = conn.cursor()

            # First, get all security devices from device_states
            cursor.execute('''
                SELECT device_id, device_name, device_type, status_json, updated_at
                FROM device_states
                WHERE device_type IN (?, ?, ?, ?, ?, ?, ?, ?)
                ORDER BY device_name
            ''', self.SECURITY_DEVICE_TYPES)

            device_states_rows = cursor.fetchall()

            # Get latest event for each security device from history (by device_id)
            cursor.execute('''
                SELECT device_id, device_name, device_type, status_json, recorded_at,
                       ROW_NUMBER() OVER (PARTITION BY device_id ORDER BY recorded_at DESC) as rn
                FROM device_history
                WHERE device_type IN (?, ?, ?, ?, ?, ?, ?, ?)
            ''', self.SECURITY_DEVICE_TYPES)

            history_rows = cursor.fetchall()

            # Also get latest event by device_name (for cases where device_id differs)
            cursor.execute('''
                SELECT device_id, device_name, device_type, status_json, recorded_at,
                       ROW_NUMBER() OVER (PARTITION BY device_name ORDER BY recorded_at DESC) as rn
                FROM device_history
                WHERE device_type IN (?, ?, ?, ?, ?, ?, ?, ?)
            ''', self.SECURITY_DEVICE_TYPES)

            history_by_name_rows = cursor.fetchall()
            conn.close()

            # Build maps of latest history per device (by id and by name)
            latest_history_by_id = {}
            for row in history_rows:
                if row['rn'] == 1:  # Latest entry
                    latest_history_by_id[row['device_id']] = {
                        'status_json': row['status_json'],
                        'recorded_at': row['recorded_at']
                    }

            latest_history_by_name = {}
            for row in history_by_name_rows:
                if row['rn'] == 1:  # Latest entry
                    latest_history_by_name[row['device_name']] = {
                        'status_json': row['status_json'],
                        'recorded_at': row['recorded_at']
                    }

            for row in device_states_rows:
                status = json.loads(row['status_json']) if row['status_json'] else {}
                updated_at = row['updated_at']
                device_id = row['device_id']
                device_name = row['device_name']

                # Try to find history by device_id first, then by device_name
                hist = latest_history_by_id.get(device_id) or latest_history_by_name.get(device_name)

                if hist:
                    hist_status = json.loads(hist['status_json']) if hist['status_json'] else {}
                    # Merge history status into current status (history takes precedence for state fields)
                    for key in ['lockState', 'openState', 'moveDetected', 'brightness']:
                        if key in hist_status:
                            status[key] = hist_status[key]
                    # Use more recent timestamp
                    if hist['recorded_at'] and (not updated_at or hist['recorded_at'] > updated_at):
                        updated_at = hist['recorded_at']

                device_data = {
                    'device_id': device_id,
                    'device_name': device_name,
                    'device_type': row['device_type'],
                    'status': status,
                    'updated_at': updated_at,
                    'display_status': self._get_security_display_status(row['device_type'], status)
                }
                result['security'].append(device_data)

            # Also add devices that are only in history (not in device_states)
            seen_names = {d['device_name'] for d in result['security']}
            for row in history_by_name_rows:
                if row['rn'] == 1 and row['device_name'] not in seen_names:
                    status = json.loads(row['status_json']) if row['status_json'] else {}
                    device_data = {
                        'device_id': row['device_id'],
                        'device_name': row['device_name'],
                        'device_type': row['device_type'],
                        'status': status,
                        'updated_at': row['recorded_at'],
                        'display_status': self._get_security_display_status(row['device_type'], status)
                    }
                    result['security'].append(device_data)

        except Exception as e:
            logging.error("Error getting security devices: %s", e)

        # Build sensor list for filtering (will be populated below)
        result['sensor_list'] = {
            'security': [{'id': d['device_id'], 'name': d['device_name']} for d in result['security']],
            'switchbot': [],
            'netatmo': []
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
                    'device_id': device_id,
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

                # Add to sensor list for filtering
                is_outdoor = self._is_outdoor_sensor(device_name)
                result['sensor_list']['switchbot'].append({
                    'id': device_id,
                    'name': device_name,
                    'category': 'outdoor' if is_outdoor else 'indoor'
                })

                # Classify as outdoor or indoor
                if is_outdoor:
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
                    'device_id': device_id,
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

                # Determine category for sensor list
                if module_type == 'NAModule2':
                    category = 'wind'
                elif module_type == 'NAModule3':
                    category = 'rain'
                elif is_outdoor:
                    category = 'outdoor'
                else:
                    category = 'indoor'

                # Add to sensor list for filtering
                result['sensor_list']['netatmo'].append({
                    'id': device_id,
                    'name': device_name,
                    'category': category
                })

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

    def _get_security_display_status(self, device_type, status):
        """Get display-friendly status for security devices."""
        if 'Lock' in device_type:
            lock_state = status.get('lockState', '').lower()  # Handle both LOCKED and locked
            if lock_state == 'locked':
                return {'text': '施錠', 'icon': '🔒', 'color': 'green'}
            elif lock_state == 'unlocked':
                return {'text': '解錠', 'icon': '🔓', 'color': 'red'}
            elif lock_state == 'jammed':
                return {'text': 'ジャム', 'icon': '⚠️', 'color': 'orange'}
            return {'text': '不明', 'icon': '❓', 'color': 'gray'}

        elif device_type == 'Contact Sensor':
            open_state = status.get('openState', '').lower()  # Handle both OPEN and open
            if open_state == 'open':
                return {'text': '開', 'icon': '🚪', 'color': 'orange'}
            elif open_state in ('close', 'closed'):
                return {'text': '閉', 'icon': '🚪', 'color': 'green'}
            return {'text': '不明', 'icon': '❓', 'color': 'gray'}

        elif device_type == 'Motion Sensor':
            if status.get('moveDetected', False):
                return {'text': '検知中', 'icon': '👁', 'color': 'orange'}
            return {'text': '待機中', 'icon': '👁', 'color': 'green'}

        elif device_type == 'Video Doorbell':
            return {'text': '待機中', 'icon': '🔔', 'color': 'green'}

        return {'text': '-', 'icon': '📱', 'color': 'gray'}

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
        /* Security status colors */
        .status-green { color: #4caf50; }
        .status-red { color: #f44336; }
        .status-orange { color: #ff9800; }
        .status-gray { color: #9e9e9e; }
        /* Security card */
        .security-card {
            background: #16213e;
            border-radius: 12px;
            padding: 15px 20px;
            display: flex;
            align-items: center;
            gap: 15px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        }
        .security-card .icon {
            font-size: 2em;
        }
        .security-card .info {
            flex: 1;
        }
        .security-card .info .name {
            font-size: 0.95em;
            color: #4fc3f7;
            margin-bottom: 4px;
        }
        .security-card .info .type {
            font-size: 0.75em;
            color: #888;
        }
        .security-card .status {
            font-size: 1.2em;
            font-weight: bold;
            text-align: right;
        }
        .security-card .updated {
            font-size: 0.7em;
            color: #666;
            margin-top: 4px;
        }
        /* Filter bar */
        .filter-bar {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
            padding: 15px;
            background: #16213e;
            border-radius: 8px;
        }
        .filter-bar label {
            display: flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
            padding: 6px 12px;
            border-radius: 20px;
            background: #1a1a2e;
            font-size: 0.85em;
            transition: background 0.2s;
        }
        .filter-bar label:hover {
            background: #2a2a4e;
        }
        .filter-bar input[type="checkbox"] {
            width: 16px;
            height: 16px;
        }
        /* Multi-select dropdown */
        .filter-dropdown {
            position: relative;
            display: inline-block;
        }
        .filter-dropdown-btn {
            background: #1a1a2e;
            border: 1px solid #333;
            color: #eee;
            padding: 8px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85em;
            display: flex;
            align-items: center;
            gap: 8px;
            min-width: 150px;
            justify-content: space-between;
        }
        .filter-dropdown-btn:hover {
            background: #2a2a4e;
        }
        .filter-dropdown-btn .count {
            background: #4fc3f7;
            color: #1a1a2e;
            padding: 2px 6px;
            border-radius: 10px;
            font-size: 0.8em;
            font-weight: bold;
        }
        .filter-dropdown-content {
            display: none;
            position: absolute;
            top: 100%;
            left: 0;
            background: #16213e;
            min-width: 220px;
            max-height: 300px;
            overflow-y: auto;
            box-shadow: 0 8px 16px rgba(0,0,0,0.4);
            z-index: 100;
            border-radius: 8px;
            margin-top: 4px;
            border: 1px solid #333;
        }
        .filter-dropdown-content.show {
            display: block;
        }
        .filter-dropdown-content label {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 10px 12px;
            cursor: pointer;
            font-size: 0.85em;
            border-bottom: 1px solid #333;
            background: transparent;
            border-radius: 0;
        }
        .filter-dropdown-content label:last-child {
            border-bottom: none;
        }
        .filter-dropdown-content label:hover {
            background: #1a1a2e;
        }
        .filter-dropdown-content .select-all {
            background: #1a1a2e;
            font-weight: bold;
            border-bottom: 2px solid #333;
        }
        .filter-dropdown-content .category-header {
            background: #0f1524;
            color: #4fc3f7;
            font-size: 0.75em;
            text-transform: uppercase;
            padding: 6px 12px;
            border-bottom: 1px solid #333;
        }
        /* Toast notifications */
        .toast-container {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1000;
            display: flex;
            flex-direction: column;
            gap: 10px;
            max-width: 350px;
        }
        .toast {
            background: #263238;
            border-left: 4px solid #4fc3f7;
            border-radius: 8px;
            padding: 15px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
            animation: slideIn 0.3s ease;
            display: flex;
            align-items: flex-start;
            gap: 12px;
        }
        .toast.security {
            border-left-color: #ff9800;
        }
        .toast .icon {
            font-size: 1.5em;
        }
        .toast .content {
            flex: 1;
        }
        .toast .message {
            font-size: 0.9em;
            margin-bottom: 4px;
        }
        .toast .time {
            font-size: 0.75em;
            color: #888;
        }
        .toast .close {
            background: none;
            border: none;
            color: #888;
            cursor: pointer;
            font-size: 1.2em;
            padding: 0;
            line-height: 1;
        }
        .toast .close:hover {
            color: #fff;
        }
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        @keyframes slideOut {
            from { transform: translateX(0); opacity: 1; }
            to { transform: translateX(100%); opacity: 0; }
        }
        .toast.hiding {
            animation: slideOut 0.3s ease forwards;
        }
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
    <!-- Toast notification container -->
    <div class="toast-container" id="toastContainer"></div>

    <div class="header">
        <h1>Environment Dashboard</h1>
        <div class="last-updated" id="lastUpdated">Loading...</div>
    </div>

    <!-- Filter bar -->
    <div class="filter-bar" id="filterBar">
        <!-- Section filters -->
        <label><input type="checkbox" id="filter-security" checked> 🔐 Security</label>
        <label><input type="checkbox" id="filter-outdoor" checked> 🌳 Outdoor</label>
        <label><input type="checkbox" id="filter-indoor" checked> 🏠 Indoor</label>
        <label><input type="checkbox" id="filter-wind" checked> 🌬️ Wind</label>
        <label><input type="checkbox" id="filter-rain" checked> 🌧️ Rain</label>

        <!-- Sensor dropdowns (populated dynamically) -->
        <div class="filter-dropdown" id="dropdown-security" style="display:none;">
            <button class="filter-dropdown-btn" onclick="toggleDropdown('security')">
                🔐 Sensors <span class="count" id="count-security">0</span> ▼
            </button>
            <div class="filter-dropdown-content" id="dropdown-content-security"></div>
        </div>
        <div class="filter-dropdown" id="dropdown-switchbot" style="display:none;">
            <button class="filter-dropdown-btn" onclick="toggleDropdown('switchbot')">
                SwitchBot <span class="count" id="count-switchbot">0</span> ▼
            </button>
            <div class="filter-dropdown-content" id="dropdown-content-switchbot"></div>
        </div>
        <div class="filter-dropdown" id="dropdown-netatmo" style="display:none;">
            <button class="filter-dropdown-btn" onclick="toggleDropdown('netatmo')">
                Netatmo <span class="count" id="count-netatmo">0</span> ▼
            </button>
            <div class="filter-dropdown-content" id="dropdown-content-netatmo"></div>
        </div>
    </div>

    <div id="content">
        <div class="loading">Loading sensor data...</div>
    </div>

    <script>
        // Chart.js default configuration
        Chart.defaults.color = '#888';
        Chart.defaults.borderColor = '#333';

        // Store current data for filtering
        let currentData = null;

        // Filter state
        const filters = {
            security: true,
            outdoor: true,
            indoor: true,
            wind: true,
            rain: true
        };

        // Sensor-level filters (device IDs to show; null = show all)
        const sensorFilters = {
            security: null,  // null means show all
            switchbot: null,
            netatmo: null
        };

        // Initialize filter checkboxes
        document.querySelectorAll('.filter-bar input[id^="filter-"]').forEach(checkbox => {
            const key = checkbox.id.replace('filter-', '');
            checkbox.addEventListener('change', () => {
                filters[key] = checkbox.checked;
                if (currentData) renderDashboard(currentData);
            });
        });

        // Toggle dropdown visibility
        function toggleDropdown(type) {
            const content = document.getElementById('dropdown-content-' + type);
            const allContents = document.querySelectorAll('.filter-dropdown-content');
            allContents.forEach(c => {
                if (c !== content) c.classList.remove('show');
            });
            content.classList.toggle('show');
        }

        // Close dropdowns when clicking outside
        document.addEventListener('click', function(e) {
            if (!e.target.closest('.filter-dropdown')) {
                document.querySelectorAll('.filter-dropdown-content').forEach(c => {
                    c.classList.remove('show');
                });
            }
        });

        // Build sensor dropdown for a category
        function buildSensorDropdown(type, sensors) {
            const container = document.getElementById('dropdown-content-' + type);
            const dropdown = document.getElementById('dropdown-' + type);
            const countEl = document.getElementById('count-' + type);

            if (!sensors || sensors.length === 0) {
                dropdown.style.display = 'none';
                return;
            }

            dropdown.style.display = 'inline-block';

            // Group by category if available
            const byCategory = {};
            sensors.forEach(s => {
                const cat = s.category || 'other';
                if (!byCategory[cat]) byCategory[cat] = [];
                byCategory[cat].push(s);
            });

            let html = '';
            // Select All option
            html += '<label class="select-all">';
            html += '<input type="checkbox" id="sensor-all-' + type + '" checked onchange="toggleAllSensors(\\'' + type + '\\', this.checked)"> ';
            html += 'すべて選択</label>';

            // Sensors grouped by category
            const categoryNames = {
                outdoor: '🌳 屋外',
                indoor: '🏠 室内',
                wind: '🌬️ 風速',
                rain: '🌧️ 雨量',
                other: '📱 その他'
            };

            for (const cat of Object.keys(byCategory).sort()) {
                if (Object.keys(byCategory).length > 1) {
                    html += '<div class="category-header">' + (categoryNames[cat] || cat) + '</div>';
                }
                for (const sensor of byCategory[cat]) {
                    const escapedId = sensor.id.replace(/'/g, "\\\\'");
                    html += '<label>';
                    html += '<input type="checkbox" data-sensor-type="' + type + '" data-sensor-id="' + sensor.id + '" checked ';
                    html += 'onchange="updateSensorFilter(\\'' + type + '\\')"> ';
                    html += sensor.name + '</label>';
                }
            }

            container.innerHTML = html;
            updateSensorCount(type);
        }

        // Toggle all sensors in a category
        function toggleAllSensors(type, checked) {
            const checkboxes = document.querySelectorAll('input[data-sensor-type="' + type + '"]');
            checkboxes.forEach(cb => cb.checked = checked);
            updateSensorFilter(type);
        }

        // Update sensor filter state
        function updateSensorFilter(type) {
            const checkboxes = document.querySelectorAll('input[data-sensor-type="' + type + '"]');
            const allCheckbox = document.getElementById('sensor-all-' + type);
            const selectedIds = [];
            let allChecked = true;

            checkboxes.forEach(cb => {
                if (cb.checked) {
                    selectedIds.push(cb.dataset.sensorId);
                } else {
                    allChecked = false;
                }
            });

            if (allCheckbox) {
                allCheckbox.checked = allChecked;
            }

            // If all selected, use null (show all); otherwise use selectedIds
            sensorFilters[type] = allChecked ? null : selectedIds;

            updateSensorCount(type);

            if (currentData) renderDashboard(currentData);
        }

        // Update the count badge
        function updateSensorCount(type) {
            const checkboxes = document.querySelectorAll('input[data-sensor-type="' + type + '"]');
            const countEl = document.getElementById('count-' + type);
            let count = 0;
            checkboxes.forEach(cb => { if (cb.checked) count++; });
            if (countEl) {
                countEl.textContent = count + '/' + checkboxes.length;
            }
        }

        // Check if a sensor should be shown
        function isSensorVisible(type, deviceId) {
            if (sensorFilters[type] === null) return true;
            return sensorFilters[type].includes(deviceId);
        }

        // Fetch data and render dashboard
        let dropdownsInitialized = false;

        async function loadDashboard() {
            try {
                const response = await fetch('/api/data');
                const data = await response.json();
                currentData = data;

                // Build sensor dropdowns (only once)
                if (!dropdownsInitialized && data.sensor_list) {
                    buildSensorDropdown('security', data.sensor_list.security);
                    buildSensorDropdown('switchbot', data.sensor_list.switchbot);
                    buildSensorDropdown('netatmo', data.sensor_list.netatmo);
                    dropdownsInitialized = true;
                }

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

        function formatTimeShort(isoString) {
            if (!isoString) return '-';
            const date = new Date(isoString);
            return date.toLocaleString('ja-JP', {
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

            // Security section (apply sensor filter)
            if (filters.security && data.security && data.security.length > 0) {
                const filteredSecurity = data.security.filter(d => isSensorVisible('security', d.device_id));
                if (filteredSecurity.length > 0) {
                    html += renderSecuritySection(filteredSecurity);
                }
            }

            // Outdoor section (apply sensor filters)
            if (filters.outdoor) {
                const outdoorDevices = [
                    ...data.switchbot.outdoor
                        .filter(d => isSensorVisible('switchbot', d.device_id))
                        .map(d => ({...d, source: 'SB'})),
                    ...data.netatmo.outdoor
                        .filter(d => isSensorVisible('netatmo', d.device_id))
                        .map(d => ({...d, source: 'NA'}))
                ];
                if (outdoorDevices.length > 0) {
                    html += renderSection('Outdoor', outdoorDevices, ['temperature', 'humidity']);
                }
            }

            // Indoor section (apply sensor filters)
            if (filters.indoor) {
                const indoorDevices = [
                    ...data.switchbot.indoor
                        .filter(d => isSensorVisible('switchbot', d.device_id))
                        .map(d => ({...d, source: 'SB'})),
                    ...data.netatmo.indoor
                        .filter(d => isSensorVisible('netatmo', d.device_id))
                        .map(d => ({...d, source: 'NA'}))
                ];
                if (indoorDevices.length > 0) {
                    html += renderSection('Indoor', indoorDevices, ['temperature', 'humidity', 'co2', 'pressure', 'noise']);
                }
            }

            // Wind section (apply sensor filter)
            if (filters.wind && data.netatmo.wind.length > 0) {
                const filteredWind = data.netatmo.wind.filter(d => isSensorVisible('netatmo', d.device_id));
                if (filteredWind.length > 0) {
                    html += renderWindSection(filteredWind);
                }
            }

            // Rain section (apply sensor filter)
            if (filters.rain && data.netatmo.rain.length > 0) {
                const filteredRain = data.netatmo.rain.filter(d => isSensorVisible('netatmo', d.device_id));
                if (filteredRain.length > 0) {
                    html += renderRainSection(filteredRain);
                }
            }

            document.getElementById('content').innerHTML = html;

            // Render charts after DOM update
            setTimeout(() => {
                renderCharts(data);
            }, 100);
        }

        function renderSecuritySection(devices) {
            let html = '<div class="section" data-section="security">';
            html += '<h2>🔐 Security</h2>';
            html += '<div class="cards">';

            for (const device of devices) {
                const ds = device.display_status || {};
                const statusColor = 'status-' + (ds.color || 'gray');

                html += '<div class="security-card">';
                html += '<div class="icon">' + (ds.icon || '📱') + '</div>';
                html += '<div class="info">';
                html += '<div class="name">' + device.device_name + '</div>';
                html += '<div class="type">' + device.device_type + '</div>';
                html += '</div>';
                html += '<div class="status ' + statusColor + '">';
                html += (ds.text || '-');
                html += '<div class="updated">' + formatTimeShort(device.updated_at) + '</div>';
                html += '</div>';
                html += '</div>';
            }

            html += '</div></div>';
            return html;
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

            // Outdoor charts (if filter enabled, apply sensor filter)
            if (filters.outdoor) {
                const outdoorDevices = [
                    ...data.switchbot.outdoor
                        .filter(d => isSensorVisible('switchbot', d.device_id))
                        .map(d => ({...d, source: 'SB'})),
                    ...data.netatmo.outdoor
                        .filter(d => isSensorVisible('netatmo', d.device_id))
                        .map(d => ({...d, source: 'NA'}))
                ];
                if (outdoorDevices.length > 0) {
                    renderLineChart('chart-outdoor-temp', outdoorDevices, 'temperature', colors);
                    renderLineChart('chart-outdoor-humidity', outdoorDevices, 'humidity', colors);
                }
            }

            // Indoor charts (if filter enabled, apply sensor filter)
            if (filters.indoor) {
                const indoorDevices = [
                    ...data.switchbot.indoor
                        .filter(d => isSensorVisible('switchbot', d.device_id))
                        .map(d => ({...d, source: 'SB'})),
                    ...data.netatmo.indoor
                        .filter(d => isSensorVisible('netatmo', d.device_id))
                        .map(d => ({...d, source: 'NA'}))
                ];
                if (indoorDevices.length > 0) {
                    renderLineChart('chart-indoor-temp', indoorDevices, 'temperature', colors);
                    renderLineChart('chart-indoor-humidity', indoorDevices, 'humidity', colors);
                    renderLineChart('chart-indoor-co2', indoorDevices, 'co2', colors);
                    renderLineChart('chart-indoor-pressure', indoorDevices, 'pressure', colors);
                    renderLineChart('chart-indoor-noise', indoorDevices, 'noise', colors);
                }
            }

            // Wind chart (if filter enabled, apply sensor filter)
            if (filters.wind && data.netatmo.wind.length > 0) {
                const filteredWind = data.netatmo.wind.filter(d => isSensorVisible('netatmo', d.device_id));
                if (filteredWind.length > 0) {
                    renderWindChart('chart-wind', filteredWind);
                }
            }

            // Rain chart (if filter enabled, apply sensor filter)
            if (filters.rain && data.netatmo.rain.length > 0) {
                const filteredRain = data.netatmo.rain.filter(d => isSensorVisible('netatmo', d.device_id));
                if (filteredRain.length > 0) {
                    renderRainChart('chart-rain', filteredRain);
                }
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

        // ========== Toast Notification System ==========
        let lastEventTimestamp = null;
        const shownEventIds = new Set();
        let isFirstPoll = true;  // Skip toast on first poll

        function showToast(message, icon = '🔔', type = 'security') {
            const container = document.getElementById('toastContainer');
            const toast = document.createElement('div');
            toast.className = 'toast ' + type;

            const now = new Date();
            const timeStr = now.toLocaleString('ja-JP', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

            toast.innerHTML = `
                <div class="icon">${icon}</div>
                <div class="content">
                    <div class="message">${message}</div>
                    <div class="time">${timeStr}</div>
                </div>
                <button class="close" onclick="this.parentElement.remove()">×</button>
            `;

            container.appendChild(toast);

            // Auto-remove after 10 seconds
            setTimeout(() => {
                if (toast.parentElement) {
                    toast.classList.add('hiding');
                    setTimeout(() => toast.remove(), 300);
                }
            }, 10000);
        }

        async function pollSecurityEvents() {
            try {
                let url = '/api/events';
                if (lastEventTimestamp) {
                    url += '?since=' + encodeURIComponent(lastEventTimestamp);
                }

                const response = await fetch(url);
                const data = await response.json();

                if (data.events && data.events.length > 0) {
                    // Process events in reverse order (oldest first)
                    const newEvents = data.events
                        .filter(e => !shownEventIds.has(e.id))
                        .reverse();

                    for (const event of newEvents) {
                        shownEventIds.add(event.id);

                        // Only show toast after first poll (skip initial load)
                        if (!isFirstPoll) {
                            // Extract icon from message or use default
                            let icon = '🔔';
                            const firstChar = event.message.charAt(0);
                            if (firstChar && firstChar.codePointAt(0) > 0x1F300) {
                                icon = firstChar;
                            }

                            showToast(event.message, icon, 'security');
                        }

                        // Update last timestamp
                        if (!lastEventTimestamp || event.recorded_at > lastEventTimestamp) {
                            lastEventTimestamp = event.recorded_at;
                        }
                    }

                    // After first poll, enable toast notifications
                    isFirstPoll = false;
                }

                // Keep only last 100 event IDs in memory
                if (shownEventIds.size > 100) {
                    const idsArray = Array.from(shownEventIds);
                    shownEventIds.clear();
                    idsArray.slice(-100).forEach(id => shownEventIds.add(id));
                }

            } catch (error) {
                console.error('Error polling security events:', error);
            }
        }

        // Load on page ready
        loadDashboard();

        // Initial security events poll
        pollSecurityEvents();

        // Auto-refresh every 30 seconds (data only, no page reload)
        setInterval(() => {
            console.log('Refreshing data...');
            loadDashboard();
        }, 30000);

        // Poll security events every 5 seconds for real-time notifications
        setInterval(pollSecurityEvents, 5000);
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
