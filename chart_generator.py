# -*- coding: utf-8 -*-
"""
Chart generator using QuickChart.io API.
Python 3.7+ compatible, requires only requests library.
"""
import json
import logging
from datetime import datetime, timedelta
try:
    from urllib.parse import urlencode, quote
except ImportError:
    from urllib import urlencode, quote

import requests


def downsample_sensor_data(sensor_data, interval_seconds):
    """
    Downsample sensor data by averaging values within each interval.

    Args:
        sensor_data: List of sensor readings with 'recorded_at', 'temperature',
                     'humidity', 'co2' keys
        interval_seconds: Interval in seconds for grouping data points

    Returns:
        list: Downsampled sensor data with averaged values
    """
    if not sensor_data or interval_seconds <= 0:
        return sensor_data

    # Parse timestamps and group by interval
    from datetime import datetime

    grouped = {}  # {interval_key: [readings]}

    for reading in sensor_data:
        timestamp = reading['recorded_at']
        try:
            # Parse ISO format timestamp
            if 'T' in timestamp:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            else:
                dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')

            # Calculate interval key (seconds since midnight, rounded to interval)
            seconds_since_midnight = dt.hour * 3600 + dt.minute * 60 + dt.second
            interval_key = (seconds_since_midnight // interval_seconds) * interval_seconds

            if interval_key not in grouped:
                grouped[interval_key] = []
            grouped[interval_key].append(reading)
        except (ValueError, AttributeError) as e:
            # Skip invalid timestamps
            continue

    # Calculate averages for each interval
    result = []
    for interval_key in sorted(grouped.keys()):
        readings = grouped[interval_key]
        if not readings:
            continue

        # Use the first reading's timestamp as the representative time
        representative_timestamp = readings[0]['recorded_at']

        # Calculate averages (ignore None values)
        temps = [r['temperature'] for r in readings if r.get('temperature') is not None]
        humids = [r['humidity'] for r in readings if r.get('humidity') is not None]
        co2s = [r['co2'] for r in readings if r.get('co2') is not None]
        pressures = [r['pressure'] for r in readings if r.get('pressure') is not None]
        noises = [r['noise'] for r in readings if r.get('noise') is not None]
        winds = [r['wind_strength'] for r in readings if r.get('wind_strength') is not None]
        gusts = [r['gust_strength'] for r in readings if r.get('gust_strength') is not None]
        wind_angles = [r['wind_angle'] for r in readings if r.get('wind_angle') is not None]
        rains = [r['rain'] for r in readings if r.get('rain') is not None]
        rains_1h = [r['rain_1h'] for r in readings if r.get('rain_1h') is not None]
        rains_24h = [r['rain_24h'] for r in readings if r.get('rain_24h') is not None]

        result.append({
            'recorded_at': representative_timestamp,
            'temperature': round(sum(temps) / len(temps), 1) if temps else None,
            'humidity': round(sum(humids) / len(humids)) if humids else None,
            'co2': round(sum(co2s) / len(co2s)) if co2s else None,
            'pressure': round(sum(pressures) / len(pressures), 1) if pressures else None,
            'noise': round(sum(noises) / len(noises)) if noises else None,
            'wind_strength': round(sum(winds) / len(winds)) if winds else None,
            'gust_strength': round(sum(gusts) / len(gusts)) if gusts else None,
            'wind_angle': round(sum(wind_angles) / len(wind_angles)) if wind_angles else None,
            'rain': round(sum(rains) / len(rains), 1) if rains else None,
            'rain_1h': round(sum(rains_1h) / len(rains_1h), 1) if rains_1h else None,
            'rain_24h': round(sum(rains_24h) / len(rains_24h), 1) if rains_24h else None,
        })

    return result


def utc_to_jst(time_str):
    """
    Convert UTC time string (HH:MM) to JST (UTC+9).

    Args:
        time_str: Time in HH:MM format (UTC)

    Returns:
        str: Time in HH:MM format (JST)
    """
    try:
        hour, minute = map(int, time_str.split(':'))
        # Add 9 hours for JST
        hour = (hour + 9) % 24
        return '{:02d}:{:02d}'.format(hour, minute)
    except (ValueError, AttributeError):
        return time_str


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

        # Extract time labels (HH:MM format, converted to JST)
        labels = []
        temperatures = []
        humidities = []
        co2_values = []

        for reading in sensor_data:
            # Parse timestamp and format as HH:MM (JST)
            timestamp = reading['recorded_at']
            if 'T' in timestamp:
                time_utc = timestamp.split('T')[1][:5]
            else:
                time_utc = timestamp[11:16]
            time_jst = utc_to_jst(time_utc)
            labels.append(time_jst)

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

    def generate_multi_device_chart(self, devices_data, metric, date_str, use_short_url=True, interval_seconds=None):
        """
        Generate chart comparing multiple devices.

        Args:
            devices_data: Dict of {device_name: sensor_data_list}
            metric: Metric to compare ('temperature', 'humidity', 'co2')
            date_str: Date string for title
            use_short_url: Use short URL
            interval_seconds: Interval in seconds for downsampling data points.
                              If specified, data will be averaged within each interval.

        Returns:
            str: Chart URL
        """
        # Downsample data if interval is specified
        if interval_seconds and interval_seconds > 0:
            devices_data = {
                name: downsample_sensor_data(data, interval_seconds)
                for name, data in devices_data.items()
            }

        # More colors for multiple devices
        colors = [
            ('rgb(255, 99, 132)', 'rgba(255, 99, 132, 0.1)'),   # Red
            ('rgb(54, 162, 235)', 'rgba(54, 162, 235, 0.1)'),   # Blue
            ('rgb(75, 192, 192)', 'rgba(75, 192, 192, 0.1)'),   # Teal
            ('rgb(255, 159, 64)', 'rgba(255, 159, 64, 0.1)'),   # Orange
            ('rgb(153, 102, 255)', 'rgba(153, 102, 255, 0.1)'), # Purple
            ('rgb(255, 206, 86)', 'rgba(255, 206, 86, 0.1)'),   # Yellow
            ('rgb(231, 76, 60)', 'rgba(231, 76, 60, 0.1)'),     # Dark Red
            ('rgb(46, 204, 113)', 'rgba(46, 204, 113, 0.1)'),   # Green
            ('rgb(52, 73, 94)', 'rgba(52, 73, 94, 0.1)'),       # Dark Gray
            ('rgb(155, 89, 182)', 'rgba(155, 89, 182, 0.1)'),   # Violet
        ]

        # Find all unique time labels (convert UTC to JST)
        all_times = set()
        for data in devices_data.values():
            for reading in data:
                timestamp = reading['recorded_at']
                if 'T' in timestamp:
                    time_utc = timestamp.split('T')[1][:5]
                else:
                    time_utc = timestamp[11:16]
                time_jst = utc_to_jst(time_utc)
                all_times.add(time_jst)

        labels = sorted(list(all_times))

        datasets = []
        for i, (device_name, data) in enumerate(devices_data.items()):
            # Build time -> value mapping (using JST)
            time_values = {}
            for reading in data:
                timestamp = reading['recorded_at']
                if 'T' in timestamp:
                    time_utc = timestamp.split('T')[1][:5]
                else:
                    time_utc = timestamp[11:16]
                time_jst = utc_to_jst(time_utc)
                time_values[time_jst] = reading.get(metric)

            # Fill data array
            values = [time_values.get(t) for t in labels]

            # Skip if all values are None
            if all(v is None for v in values):
                continue

            color_idx = i % len(colors)
            datasets.append({
                'label': device_name,
                'data': values,
                'borderColor': colors[color_idx][0],
                'backgroundColor': colors[color_idx][1],
                'fill': False,
                'tension': 0.3,
                'spanGaps': True  # Connect points across null values
            })

        # Skip if no datasets have data
        if not datasets:
            return None

        metric_labels = {
            'temperature': '温度 (°C)',
            'humidity': '湿度 (%)',
            'co2': 'CO2 (ppm)',
            'pressure': '気圧 (hPa)',
            'noise': '騒音 (dB)',
            'wind_strength': '風速 (km/h)',
            'gust_strength': '突風 (km/h)',
            'rain': '雨量 (mm)',
            'rain_1h': '雨量/1h (mm)',
            'rain_24h': '雨量/24h (mm)'
        }

        metric_units = {
            'temperature': '°C',
            'humidity': '%',
            'co2': 'ppm',
            'pressure': 'hPa',
            'noise': 'dB',
            'wind_strength': 'km/h',
            'gust_strength': 'km/h',
            'rain': 'mm',
            'rain_1h': 'mm',
            'rain_24h': 'mm'
        }

        options = {
            'scales': {
                'y': {
                    'title': {
                        'display': True,
                        'text': metric_units.get(metric, '')
                    }
                }
            },
            'plugins': {
                'legend': {
                    'display': True,
                    'position': 'bottom'
                }
            }
        }

        # Add CO2 threshold lines
        if metric == 'co2':
            options['scales']['y']['min'] = 400
            options['plugins']['annotation'] = {
                'annotations': {
                    'warning': {
                        'type': 'line',
                        'yMin': 1000,
                        'yMax': 1000,
                        'borderColor': 'orange',
                        'borderWidth': 2,
                        'borderDash': [5, 5]
                    },
                    'danger': {
                        'type': 'line',
                        'yMin': 1500,
                        'yMax': 1500,
                        'borderColor': 'red',
                        'borderWidth': 2,
                        'borderDash': [5, 5]
                    }
                }
            }

        config = self._create_chart_config(
            'line',
            labels,
            datasets,
            title='{} ({})'.format(metric_labels.get(metric, metric), date_str),
            options=options
        )

        return self.get_chart_url(config, use_short_url)

    def generate_rain_chart(self, devices_data, date_str, use_short_url=True, interval_seconds=None):
        """
        Generate combined rain chart with bar (1h) and line (24h).

        Args:
            devices_data: Dict of {device_name: sensor_data_list}
            date_str: Date string for title
            use_short_url: Use short URL
            interval_seconds: Interval for downsampling

        Returns:
            str: Chart URL
        """
        # Downsample if needed
        if interval_seconds and interval_seconds > 0:
            devices_data = {
                name: downsample_sensor_data(data, interval_seconds)
                for name, data in devices_data.items()
            }

        # Find all unique time labels
        all_times = set()
        for data in devices_data.values():
            for reading in data:
                timestamp = reading['recorded_at']
                if 'T' in timestamp:
                    time_utc = timestamp.split('T')[1][:5]
                else:
                    time_utc = timestamp[11:16]
                time_jst = utc_to_jst(time_utc)
                all_times.add(time_jst)

        labels = sorted(list(all_times))
        datasets = []

        # Colors
        bar_color = 'rgba(54, 162, 235, 0.7)'  # Blue for 1h rain
        line_color = 'rgb(255, 99, 132)'       # Red for 24h rain

        for device_name, data in devices_data.items():
            # Build time -> value mapping
            time_values_1h = {}
            time_values_24h = {}
            for reading in data:
                timestamp = reading['recorded_at']
                if 'T' in timestamp:
                    time_utc = timestamp.split('T')[1][:5]
                else:
                    time_utc = timestamp[11:16]
                time_jst = utc_to_jst(time_utc)
                time_values_1h[time_jst] = reading.get('rain_1h')
                time_values_24h[time_jst] = reading.get('rain_24h')

            # 1h rain as bar
            values_1h = [time_values_1h.get(t) for t in labels]
            if any(v is not None for v in values_1h):
                datasets.append({
                    'type': 'bar',
                    'label': '{} (1h)'.format(device_name),
                    'data': values_1h,
                    'backgroundColor': bar_color,
                    'borderColor': bar_color,
                    'yAxisID': 'y'
                })

            # 24h rain as line
            values_24h = [time_values_24h.get(t) for t in labels]
            if any(v is not None for v in values_24h):
                datasets.append({
                    'type': 'line',
                    'label': '{} (24h累計)'.format(device_name),
                    'data': values_24h,
                    'borderColor': line_color,
                    'backgroundColor': 'transparent',
                    'fill': False,
                    'tension': 0.3,
                    'yAxisID': 'y1'
                })

        if not datasets:
            return None

        options = {
            'scales': {
                'y': {
                    'type': 'linear',
                    'display': True,
                    'position': 'left',
                    'title': {'display': True, 'text': '1h雨量 (mm)'},
                    'min': 0
                },
                'y1': {
                    'type': 'linear',
                    'display': True,
                    'position': 'right',
                    'title': {'display': True, 'text': '24h累計 (mm)'},
                    'min': 0,
                    'grid': {'drawOnChartArea': False}
                }
            },
            'plugins': {
                'legend': {
                    'display': True,
                    'position': 'bottom'
                }
            }
        }

        config = self._create_chart_config(
            'bar',  # Base type is bar
            labels,
            datasets,
            title='雨量 ({})'.format(date_str),
            options=options
        )

        return self.get_chart_url(config, use_short_url)

    def generate_wind_chart(self, devices_data, date_str, use_short_url=True, interval_seconds=None):
        """
        Generate wind chart with speed, gust, and direction annotations.

        Args:
            devices_data: Dict of {device_name: sensor_data_list}
            date_str: Date string for title
            use_short_url: Use short URL
            interval_seconds: Interval for downsampling

        Returns:
            str: Chart URL
        """
        # Downsample if needed
        if interval_seconds and interval_seconds > 0:
            devices_data = {
                name: downsample_sensor_data(data, interval_seconds)
                for name, data in devices_data.items()
            }

        # Find all unique time labels
        all_times = set()
        for data in devices_data.values():
            for reading in data:
                timestamp = reading['recorded_at']
                if 'T' in timestamp:
                    time_utc = timestamp.split('T')[1][:5]
                else:
                    time_utc = timestamp[11:16]
                time_jst = utc_to_jst(time_utc)
                all_times.add(time_jst)

        labels = sorted(list(all_times))
        datasets = []

        # Colors
        wind_color = 'rgb(54, 162, 235)'   # Blue for wind
        gust_color = 'rgb(255, 99, 132)'    # Red for gust

        for device_name, data in devices_data.items():
            # Build time -> value mapping
            time_wind = {}
            time_gust = {}
            time_angle = {}
            for reading in data:
                timestamp = reading['recorded_at']
                if 'T' in timestamp:
                    time_utc = timestamp.split('T')[1][:5]
                else:
                    time_utc = timestamp[11:16]
                time_jst = utc_to_jst(time_utc)
                time_wind[time_jst] = reading.get('wind_strength')
                time_gust[time_jst] = reading.get('gust_strength')
                time_angle[time_jst] = reading.get('wind_angle')

            # Wind speed
            values_wind = [time_wind.get(t) for t in labels]
            if any(v is not None for v in values_wind):
                # Create labels with direction
                point_labels = []
                for t in labels:
                    angle = time_angle.get(t)
                    if angle is not None:
                        direction = self._angle_to_direction(angle)
                        point_labels.append(direction)
                    else:
                        point_labels.append('')

                datasets.append({
                    'label': '{} 風速'.format(device_name),
                    'data': values_wind,
                    'borderColor': wind_color,
                    'backgroundColor': 'rgba(54, 162, 235, 0.1)',
                    'fill': True,
                    'tension': 0.3
                })

            # Gust speed
            values_gust = [time_gust.get(t) for t in labels]
            if any(v is not None for v in values_gust):
                datasets.append({
                    'label': '{} 突風'.format(device_name),
                    'data': values_gust,
                    'borderColor': gust_color,
                    'backgroundColor': 'transparent',
                    'fill': False,
                    'tension': 0.3,
                    'borderDash': [5, 5]
                })

        if not datasets:
            return None

        options = {
            'scales': {
                'y': {
                    'title': {'display': True, 'text': 'km/h'},
                    'min': 0
                }
            },
            'plugins': {
                'legend': {
                    'display': True,
                    'position': 'bottom'
                },
                # Add threshold lines for wind warnings
                'annotation': {
                    'annotations': {
                        'moderate': {
                            'type': 'line',
                            'yMin': 36,
                            'yMax': 36,
                            'borderColor': 'rgba(255, 206, 86, 0.8)',
                            'borderWidth': 1,
                            'borderDash': [3, 3],
                            'label': {
                                'content': 'やや強い風 (36km/h)',
                                'enabled': False
                            }
                        },
                        'strong': {
                            'type': 'line',
                            'yMin': 54,
                            'yMax': 54,
                            'borderColor': 'orange',
                            'borderWidth': 2,
                            'borderDash': [5, 5]
                        },
                        'violent': {
                            'type': 'line',
                            'yMin': 72,
                            'yMax': 72,
                            'borderColor': 'red',
                            'borderWidth': 2,
                            'borderDash': [5, 5]
                        }
                    }
                }
            }
        }

        config = self._create_chart_config(
            'line',
            labels,
            datasets,
            title='風速 ({})'.format(date_str),
            options=options
        )

        return self.get_chart_url(config, use_short_url)

    def generate_wind_direction_chart(self, devices_data, date_str, use_short_url=True, interval_seconds=None):
        """
        Generate wind direction chart showing direction over time.
        Uses scatter chart with direction labels.

        Args:
            devices_data: Dict of {device_name: sensor_data_list}
            date_str: Date string for title
            use_short_url: Use short URL
            interval_seconds: Interval for downsampling

        Returns:
            str: Chart URL
        """
        # Downsample if needed
        if interval_seconds and interval_seconds > 0:
            devices_data = {
                name: downsample_sensor_data(data, interval_seconds)
                for name, data in devices_data.items()
            }

        # Find all unique time labels
        all_times = set()
        for data in devices_data.values():
            for reading in data:
                timestamp = reading['recorded_at']
                if 'T' in timestamp:
                    time_utc = timestamp.split('T')[1][:5]
                else:
                    time_utc = timestamp[11:16]
                time_jst = utc_to_jst(time_utc)
                all_times.add(time_jst)

        labels = sorted(list(all_times))
        datasets = []

        colors = [
            'rgb(54, 162, 235)',
            'rgb(255, 99, 132)',
            'rgb(75, 192, 192)',
        ]

        for i, (device_name, data) in enumerate(devices_data.items()):
            # Build time -> angle mapping
            time_angle = {}
            for reading in data:
                timestamp = reading['recorded_at']
                if 'T' in timestamp:
                    time_utc = timestamp.split('T')[1][:5]
                else:
                    time_utc = timestamp[11:16]
                time_jst = utc_to_jst(time_utc)
                time_angle[time_jst] = reading.get('wind_angle')

            # Wind angle as line (0-360)
            values = [time_angle.get(t) for t in labels]
            if any(v is not None for v in values):
                color = colors[i % len(colors)]
                datasets.append({
                    'label': device_name,
                    'data': values,
                    'borderColor': color,
                    'backgroundColor': color,
                    'fill': False,
                    'tension': 0,
                    'spanGaps': True,
                    'pointRadius': 4
                })

        if not datasets:
            return None

        # Direction labels on Y axis
        options = {
            'scales': {
                'y': {
                    'min': 0,
                    'max': 360,
                    'ticks': {
                        'stepSize': 45,
                        'callback': 'function(value) { var dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]; return dirs[value/45]; }'
                    },
                    'title': {'display': True, 'text': '風向'}
                }
            },
            'plugins': {
                'legend': {
                    'display': True,
                    'position': 'bottom'
                }
            }
        }

        config = self._create_chart_config(
            'line',
            labels,
            datasets,
            title='風向 ({})'.format(date_str),
            options=options
        )

        return self.get_chart_url(config, use_short_url)

    def _angle_to_direction(self, angle):
        """Convert angle (0-360) to compass direction."""
        if angle is None:
            return ''
        directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                      'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
        idx = round(angle / 22.5) % 16
        return directions[idx]


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
