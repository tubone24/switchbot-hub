# -*- coding: utf-8 -*-
"""
Chart generator using QuickChart.io API.
Python 3.7+ compatible, requires only requests library.
"""
import json
import logging
try:
    from urllib.parse import urlencode, quote
except ImportError:
    from urllib import urlencode, quote

import requests


class ChartGenerator:
    """Generate chart images using QuickChart.io."""

    BASE_URL = "https://quickchart.io/chart"
    SHORT_URL_API = "https://quickchart.io/chart/create"

    def __init__(self, width=800, height=400, background_color='white'):
        """
        Initialize chart generator.

        Args:
            width: Chart width in pixels
            height: Chart height in pixels
            background_color: Background color
        """
        self.width = width
        self.height = height
        self.background_color = background_color

    def _create_chart_config(self, chart_type, labels, datasets, title=None, options=None):
        """
        Create Chart.js configuration.

        Args:
            chart_type: Type of chart (line, bar, etc.)
            labels: X-axis labels
            datasets: List of dataset configs
            title: Chart title
            options: Additional Chart.js options

        Returns:
            dict: Chart.js configuration
        """
        config = {
            'type': chart_type,
            'data': {
                'labels': labels,
                'datasets': datasets
            },
            'options': {
                'responsive': False,
                'plugins': {
                    'legend': {
                        'display': len(datasets) > 1
                    }
                }
            }
        }

        if title:
            config['options']['plugins']['title'] = {
                'display': True,
                'text': title,
                'font': {'size': 16}
            }

        if options:
            config['options'].update(options)

        return config

    def get_chart_url(self, config, use_short_url=False):
        """
        Get chart image URL.

        Args:
            config: Chart.js configuration dict
            use_short_url: Use short URL API (requires POST)

        Returns:
            str: URL to chart image
        """
        if use_short_url:
            return self._get_short_url(config)
        else:
            return self._get_direct_url(config)

    def _get_direct_url(self, config):
        """Get direct chart URL (may be long)."""
        chart_json = json.dumps(config, separators=(',', ':'))
        params = {
            'c': chart_json,
            'w': self.width,
            'h': self.height,
            'bkg': self.background_color
        }
        return "{}?{}".format(self.BASE_URL, urlencode(params))

    def _get_short_url(self, config):
        """Get shortened chart URL via API."""
        try:
            payload = {
                'chart': config,
                'width': self.width,
                'height': self.height,
                'backgroundColor': self.background_color
            }
            response = requests.post(
                self.SHORT_URL_API,
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            result = response.json()
            return result.get('url')
        except Exception as e:
            logging.warning("Failed to get short URL, using direct URL: %s", e)
            return self._get_direct_url(config)

    def generate_sensor_chart(self, sensor_data, device_name, date_str, use_short_url=True):
        """
        Generate temperature/humidity/CO2 chart for sensor data.

        Args:
            sensor_data: List of sensor readings from database
            device_name: Device name for title
            date_str: Date string for title
            use_short_url: Use short URL

        Returns:
            dict: Chart URLs for different metrics
        """
        if not sensor_data:
            return None

        # Extract time labels (HH:MM format)
        labels = []
        temperatures = []
        humidities = []
        co2_values = []

        for reading in sensor_data:
            # Parse timestamp and format as HH:MM
            timestamp = reading['recorded_at']
            if 'T' in timestamp:
                time_part = timestamp.split('T')[1][:5]
            else:
                time_part = timestamp[11:16]
            labels.append(time_part)

            temperatures.append(reading['temperature'])
            humidities.append(reading['humidity'])
            co2_values.append(reading['co2'])

        charts = {}

        # Temperature & Humidity combined chart
        if any(t is not None for t in temperatures) or any(h is not None for h in humidities):
            datasets = []

            if any(t is not None for t in temperatures):
                datasets.append({
                    'label': 'Temperature (C)',
                    'data': temperatures,
                    'borderColor': 'rgb(255, 99, 132)',
                    'backgroundColor': 'rgba(255, 99, 132, 0.1)',
                    'fill': True,
                    'tension': 0.3,
                    'yAxisID': 'y'
                })

            if any(h is not None for h in humidities):
                datasets.append({
                    'label': 'Humidity (%)',
                    'data': humidities,
                    'borderColor': 'rgb(54, 162, 235)',
                    'backgroundColor': 'rgba(54, 162, 235, 0.1)',
                    'fill': True,
                    'tension': 0.3,
                    'yAxisID': 'y1'
                })

            options = {
                'scales': {
                    'y': {
                        'type': 'linear',
                        'display': True,
                        'position': 'left',
                        'title': {'display': True, 'text': 'Temperature (C)'}
                    },
                    'y1': {
                        'type': 'linear',
                        'display': True,
                        'position': 'right',
                        'title': {'display': True, 'text': 'Humidity (%)'},
                        'grid': {'drawOnChartArea': False}
                    }
                }
            }

            config = self._create_chart_config(
                'line',
                labels,
                datasets,
                title='{} - Temperature & Humidity ({})'.format(device_name, date_str),
                options=options
            )
            charts['temp_humidity'] = self.get_chart_url(config, use_short_url)

        # CO2 chart (separate due to different scale)
        if any(c is not None for c in co2_values):
            datasets = [{
                'label': 'CO2 (ppm)',
                'data': co2_values,
                'borderColor': 'rgb(75, 192, 192)',
                'backgroundColor': 'rgba(75, 192, 192, 0.2)',
                'fill': True,
                'tension': 0.3
            }]

            # Add threshold lines
            options = {
                'scales': {
                    'y': {
                        'min': 400,
                        'title': {'display': True, 'text': 'CO2 (ppm)'}
                    }
                },
                'plugins': {
                    'annotation': {
                        'annotations': {
                            'line1': {
                                'type': 'line',
                                'yMin': 1000,
                                'yMax': 1000,
                                'borderColor': 'orange',
                                'borderWidth': 2,
                                'borderDash': [5, 5],
                                'label': {
                                    'content': 'Warning (1000ppm)',
                                    'enabled': True
                                }
                            },
                            'line2': {
                                'type': 'line',
                                'yMin': 1500,
                                'yMax': 1500,
                                'borderColor': 'red',
                                'borderWidth': 2,
                                'borderDash': [5, 5],
                                'label': {
                                    'content': 'High (1500ppm)',
                                    'enabled': True
                                }
                            }
                        }
                    }
                }
            }

            config = self._create_chart_config(
                'line',
                labels,
                datasets,
                title='{} - CO2 Level ({})'.format(device_name, date_str),
                options=options
            )
            charts['co2'] = self.get_chart_url(config, use_short_url)

        return charts

    def generate_multi_device_chart(self, devices_data, metric, date_str, use_short_url=True):
        """
        Generate chart comparing multiple devices.

        Args:
            devices_data: Dict of {device_name: sensor_data_list}
            metric: Metric to compare ('temperature', 'humidity', 'co2')
            date_str: Date string for title
            use_short_url: Use short URL

        Returns:
            str: Chart URL
        """
        colors = [
            ('rgb(255, 99, 132)', 'rgba(255, 99, 132, 0.1)'),
            ('rgb(54, 162, 235)', 'rgba(54, 162, 235, 0.1)'),
            ('rgb(75, 192, 192)', 'rgba(75, 192, 192, 0.1)'),
            ('rgb(255, 206, 86)', 'rgba(255, 206, 86, 0.1)'),
            ('rgb(153, 102, 255)', 'rgba(153, 102, 255, 0.1)'),
        ]

        # Find all unique time labels
        all_times = set()
        for data in devices_data.values():
            for reading in data:
                timestamp = reading['recorded_at']
                if 'T' in timestamp:
                    time_part = timestamp.split('T')[1][:5]
                else:
                    time_part = timestamp[11:16]
                all_times.add(time_part)

        labels = sorted(list(all_times))

        datasets = []
        for i, (device_name, data) in enumerate(devices_data.items()):
            # Build time -> value mapping
            time_values = {}
            for reading in data:
                timestamp = reading['recorded_at']
                if 'T' in timestamp:
                    time_part = timestamp.split('T')[1][:5]
                else:
                    time_part = timestamp[11:16]
                time_values[time_part] = reading.get(metric)

            # Fill data array
            values = [time_values.get(t) for t in labels]

            color_idx = i % len(colors)
            datasets.append({
                'label': device_name,
                'data': values,
                'borderColor': colors[color_idx][0],
                'backgroundColor': colors[color_idx][1],
                'fill': False,
                'tension': 0.3
            })

        metric_labels = {
            'temperature': 'Temperature (C)',
            'humidity': 'Humidity (%)',
            'co2': 'CO2 (ppm)'
        }

        config = self._create_chart_config(
            'line',
            labels,
            datasets,
            title='{} Comparison ({})'.format(metric_labels.get(metric, metric), date_str)
        )

        return self.get_chart_url(config, use_short_url)


if __name__ == '__main__':
    # Test chart generation
    generator = ChartGenerator()

    # Sample data
    test_data = [
        {'recorded_at': '2024-01-30T09:00:00', 'temperature': 22.5, 'humidity': 45, 'co2': 450},
        {'recorded_at': '2024-01-30T09:30:00', 'temperature': 23.0, 'humidity': 44, 'co2': 520},
        {'recorded_at': '2024-01-30T10:00:00', 'temperature': 23.5, 'humidity': 43, 'co2': 680},
        {'recorded_at': '2024-01-30T10:30:00', 'temperature': 24.0, 'humidity': 42, 'co2': 850},
        {'recorded_at': '2024-01-30T11:00:00', 'temperature': 24.5, 'humidity': 41, 'co2': 920},
    ]

    charts = generator.generate_sensor_chart(test_data, 'Test Sensor', '2024-01-30', use_short_url=False)

    print("Generated chart URLs:")
    for name, url in charts.items():
        print("  {}: {}".format(name, url[:100] + "..." if len(url) > 100 else url))
