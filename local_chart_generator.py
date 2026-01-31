# -*- coding: utf-8 -*-
"""
Local chart generator using matplotlib.
Python 3.7+ compatible, requires matplotlib 3.5.3.

For Raspberry Pi deployment:
1. Install Japanese fonts:
   sudo apt-get install fonts-ipaexfont fonts-ipafont

2. Install Python dependencies:
   pip install matplotlib==3.5.3 requests

Usage:
    from local_chart_generator import LocalChartGenerator, SlackImageUploader

    # Generate chart
    generator = LocalChartGenerator()
    chart_path = generator.generate_multi_device_chart(devices_data, 'temperature', '2024-01-30')

    # Upload to Slack
    uploader = SlackImageUploader(bot_token, channel_id)
    uploader.upload_file(chart_path, 'Temperature Chart', 'Daily temperature report')
"""
import logging
import os
import tempfile
from datetime import datetime

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-GUI backend for headless systems (Raspberry Pi)
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter
    import matplotlib.font_manager as fm
    MATPLOTLIB_AVAILABLE = True

    # Japanese font configuration for Raspberry Pi
    # Install fonts with: sudo apt-get install fonts-ipaexfont fonts-ipafont
    def _setup_japanese_font():
        """Setup Japanese font for matplotlib."""
        # Try to find Japanese font
        japanese_fonts = [
            'IPAexGothic',
            'IPAGothic',
            'IPA Gothic',
            'Noto Sans CJK JP',
            'TakaoPGothic',
            'VL Gothic',
        ]

        available_fonts = set([f.name for f in fm.fontManager.ttflist])

        for font in japanese_fonts:
            if font in available_fonts:
                plt.rcParams['font.family'] = font
                logging.info("Using Japanese font: %s", font)
                return True

        # Fallback: try to use system font path directly
        font_paths = [
            '/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf',
            '/usr/share/fonts/truetype/fonts-japanese-gothic.ttf',
            '/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf',
        ]

        for path in font_paths:
            if os.path.exists(path):
                try:
                    fm.fontManager.addfont(path)
                    font_prop = fm.FontProperties(fname=path)
                    plt.rcParams['font.family'] = font_prop.get_name()
                    logging.info("Using Japanese font from: %s", path)
                    return True
                except Exception as e:
                    logging.debug("Failed to add font %s: %s", path, e)

        logging.warning("No Japanese font found. Japanese text may not display correctly.")
        return False

    _setup_japanese_font()

except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logging.warning("matplotlib not available. Install with: pip install matplotlib==3.5.3")

import requests


def downsample_sensor_data(sensor_data, interval_seconds):
    """
    Downsample sensor data by averaging values within each interval.
    (Same as chart_generator.py for compatibility)
    """
    if not sensor_data or interval_seconds <= 0:
        return sensor_data

    grouped = {}
    first_dt = None

    for reading in sensor_data:
        timestamp = reading['recorded_at']
        try:
            if 'T' in timestamp:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                dt = dt.replace(tzinfo=None)
            else:
                dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')

            if first_dt is None:
                first_dt = dt

            seconds_since_start = int((dt - first_dt).total_seconds())
            interval_key = (seconds_since_start // interval_seconds) * interval_seconds

            if interval_key not in grouped:
                grouped[interval_key] = []
            grouped[interval_key].append(reading)
        except (ValueError, AttributeError):
            continue

    result = []
    for interval_key in sorted(grouped.keys()):
        readings = grouped[interval_key]
        if not readings:
            continue

        representative_timestamp = readings[0]['recorded_at']

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


class LocalChartGenerator:
    """Generate chart images locally using matplotlib."""

    # Color palette matching QuickChart version
    COLORS = [
        '#FF6384',  # Pink/Red
        '#36A2EB',  # Blue
        '#4BC0C0',  # Teal/Cyan
        '#FF9F40',  # Orange
        '#9966FF',  # Purple
        '#FFCE56',  # Yellow
        '#E74C3C',  # Dark Red
        '#2ECC71',  # Green
        '#34495E',  # Dark Gray
        '#9B59B6',  # Violet
    ]

    def __init__(self, width=1200, height=500, output_dir=None):
        """
        Initialize local chart generator.

        Args:
            width: Chart width in pixels
            height: Chart height in pixels
            output_dir: Directory to save chart images (default: temp directory)
        """
        self.width = width
        self.height = height
        self.output_dir = output_dir or tempfile.gettempdir()
        self.dpi = 100

        if not MATPLOTLIB_AVAILABLE:
            raise ImportError("matplotlib is required. Install with: pip install matplotlib==3.5.3")

    def _parse_time(self, timestamp):
        """Parse timestamp and return HH:MM string."""
        if 'T' in timestamp:
            return timestamp.split('T')[1][:5]
        else:
            return timestamp[11:16]

    def _setup_figure(self, title=None):
        """Create and setup a matplotlib figure."""
        fig_width = self.width / self.dpi
        fig_height = self.height / self.dpi
        fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=self.dpi)

        # White background
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        # Grid
        ax.grid(True, linestyle='-', alpha=0.3, color='#cccccc')
        ax.set_axisbelow(True)

        if title:
            ax.set_title(title, fontsize=14, pad=10)

        return fig, ax

    def generate_multi_device_chart(self, devices_data, metric, date_str, interval_seconds=None):
        """
        Generate chart comparing multiple devices.

        Args:
            devices_data: Dict of {device_name: sensor_data_list}
            metric: Metric to compare ('temperature', 'humidity', 'co2', etc.)
            date_str: Date string for title
            interval_seconds: Interval for downsampling

        Returns:
            str: Path to generated chart image
        """
        if not MATPLOTLIB_AVAILABLE:
            return None

        # Downsample if needed
        if interval_seconds and interval_seconds > 0:
            devices_data = {
                name: downsample_sensor_data(data, interval_seconds)
                for name, data in devices_data.items()
            }

        # Collect all time labels
        all_times = set()
        for data in devices_data.values():
            for reading in data:
                time_str = self._parse_time(reading['recorded_at'])
                all_times.add(time_str)

        labels = sorted(list(all_times))

        if not labels:
            return None

        # Check if metric needs km/h to m/s conversion
        needs_wind_conversion = metric in ('wind_strength', 'gust_strength')

        # Metric labels
        metric_labels = {
            'temperature': '温度 (°C)',
            'humidity': '湿度 (%)',
            'co2': 'CO2 (ppm)',
            'pressure': '気圧 (hPa)',
            'noise': '騒音 (dB)',
            'wind_strength': '風速 (m/s)',
            'gust_strength': '突風 (m/s)',
            'rain': '雨量 (mm)',
            'rain_1h': '雨量/1h (mm)',
            'rain_24h': '雨量/24h (mm)'
        }

        title = '{} ({})'.format(metric_labels.get(metric, metric), date_str)
        fig, ax = self._setup_figure(title)

        # Plot each device
        plotted_count = 0
        for i, (device_name, data) in enumerate(devices_data.items()):
            # Build time -> value mapping
            time_values = {}
            for reading in data:
                time_str = self._parse_time(reading['recorded_at'])
                value = reading.get(metric)
                if needs_wind_conversion and value is not None:
                    value = round(value / 3.6, 1)
                time_values[time_str] = value

            # Build values list (None for missing times)
            values = [time_values.get(t) for t in labels]

            # Skip if all None
            if all(v is None for v in values):
                continue

            color = self.COLORS[i % len(self.COLORS)]

            # Convert None values to NaN for matplotlib to handle gaps
            import math
            plot_values = [v if v is not None else float('nan') for v in values]

            ax.plot(
                labels, plot_values,
                label=device_name,
                color=color,
                linewidth=1.5,
                marker='o',
                markersize=4,
                markerfacecolor=color,
                markeredgecolor=color
            )
            plotted_count += 1

        if plotted_count == 0:
            plt.close(fig)
            return None

        # X-axis: show fewer labels if too many
        if len(labels) > 30:
            step = max(1, len(labels) // 20)
            ax.set_xticks([labels[i] for i in range(0, len(labels), step)])

        ax.tick_params(axis='x', rotation=45, labelsize=9)
        ax.tick_params(axis='y', labelsize=10)

        # Legend at top
        ax.legend(
            loc='upper center',
            bbox_to_anchor=(0.5, 1.15),
            ncol=min(plotted_count, 4),
            fontsize=9,
            frameon=False
        )

        # Y-axis label
        ax.set_ylabel(metric_labels.get(metric, ''), fontsize=11)

        # CO2 threshold lines
        if metric == 'co2':
            ax.axhline(y=1000, color='orange', linestyle='--', linewidth=1.5, alpha=0.7)
            ax.axhline(y=1500, color='red', linestyle='--', linewidth=1.5, alpha=0.7)
            ax.set_ylim(bottom=400)

        plt.tight_layout()
        plt.subplots_adjust(top=0.85)

        # Save to file
        filename = 'chart_{}_{}.png'.format(metric, date_str.replace('/', '-'))
        filepath = os.path.join(self.output_dir, filename)
        fig.savefig(filepath, dpi=self.dpi, bbox_inches='tight', facecolor='white')
        plt.close(fig)

        logging.info("Generated chart: %s", filepath)
        return filepath

    def generate_wind_chart(self, devices_data, date_str, interval_seconds=None):
        """
        Generate wind chart with speed and gust.

        Args:
            devices_data: Dict of {device_name: sensor_data_list}
            date_str: Date string for title
            interval_seconds: Interval for downsampling

        Returns:
            str: Path to generated chart image
        """
        if not MATPLOTLIB_AVAILABLE:
            return None

        # Downsample if needed
        if interval_seconds and interval_seconds > 0:
            devices_data = {
                name: downsample_sensor_data(data, interval_seconds)
                for name, data in devices_data.items()
            }

        # Collect all time labels
        all_times = set()
        for data in devices_data.values():
            for reading in data:
                time_str = self._parse_time(reading['recorded_at'])
                all_times.add(time_str)

        labels = sorted(list(all_times))
        if not labels:
            return None

        title = '風速 ({})'.format(date_str)
        fig, ax = self._setup_figure(title)

        wind_color = '#36A2EB'  # Blue
        gust_color = '#FF6384'  # Red

        plotted_count = 0
        for device_name, data in devices_data.items():
            time_wind = {}
            time_gust = {}
            for reading in data:
                time_str = self._parse_time(reading['recorded_at'])
                wind_kmh = reading.get('wind_strength')
                gust_kmh = reading.get('gust_strength')
                time_wind[time_str] = round(wind_kmh / 3.6, 1) if wind_kmh is not None else None
                time_gust[time_str] = round(gust_kmh / 3.6, 1) if gust_kmh is not None else None

            # Wind speed
            values_wind = [time_wind.get(t) if time_wind.get(t) is not None else float('nan') for t in labels]
            if not all(v != v for v in values_wind):  # Check if not all NaN
                ax.plot(
                    labels, values_wind,
                    label='{} 風速'.format(device_name),
                    color=wind_color,
                    linewidth=1.5,
                    marker='o',
                    markersize=4
                )
                ax.fill_between(labels, values_wind, alpha=0.1, color=wind_color)
                plotted_count += 1

            # Gust speed
            values_gust = [time_gust.get(t) if time_gust.get(t) is not None else float('nan') for t in labels]
            if not all(v != v for v in values_gust):
                ax.plot(
                    labels, values_gust,
                    label='{} 突風'.format(device_name),
                    color=gust_color,
                    linewidth=1.5,
                    linestyle='--',
                    marker='o',
                    markersize=4
                )
                plotted_count += 1

        if plotted_count == 0:
            plt.close(fig)
            return None

        # Threshold lines
        ax.axhline(y=10, color='#FFCE56', linestyle=':', linewidth=1, alpha=0.8)
        ax.axhline(y=15, color='orange', linestyle='--', linewidth=1.5, alpha=0.7)
        ax.axhline(y=20, color='red', linestyle='--', linewidth=1.5, alpha=0.7)

        ax.set_ylim(bottom=0)
        ax.set_ylabel('m/s', fontsize=11)

        if len(labels) > 30:
            step = max(1, len(labels) // 20)
            ax.set_xticks([labels[i] for i in range(0, len(labels), step)])

        ax.tick_params(axis='x', rotation=45, labelsize=9)

        ax.legend(
            loc='upper center',
            bbox_to_anchor=(0.5, 1.15),
            ncol=min(plotted_count, 4),
            fontsize=9,
            frameon=False
        )

        plt.tight_layout()
        plt.subplots_adjust(top=0.85)

        filename = 'chart_wind_{}.png'.format(date_str.replace('/', '-'))
        filepath = os.path.join(self.output_dir, filename)
        fig.savefig(filepath, dpi=self.dpi, bbox_inches='tight', facecolor='white')
        plt.close(fig)

        logging.info("Generated wind chart: %s", filepath)
        return filepath

    def generate_wind_direction_chart(self, devices_data, date_str, interval_seconds=None):
        """
        Generate wind direction chart.

        Args:
            devices_data: Dict of {device_name: sensor_data_list}
            date_str: Date string for title
            interval_seconds: Interval for downsampling

        Returns:
            str: Path to generated chart image
        """
        if not MATPLOTLIB_AVAILABLE:
            return None

        if interval_seconds and interval_seconds > 0:
            devices_data = {
                name: downsample_sensor_data(data, interval_seconds)
                for name, data in devices_data.items()
            }

        all_times = set()
        for data in devices_data.values():
            for reading in data:
                time_str = self._parse_time(reading['recorded_at'])
                all_times.add(time_str)

        labels = sorted(list(all_times))
        if not labels:
            return None

        title = '風向 ({})'.format(date_str)
        fig, ax = self._setup_figure(title)

        plotted_count = 0
        for i, (device_name, data) in enumerate(devices_data.items()):
            time_angle = {}
            for reading in data:
                time_str = self._parse_time(reading['recorded_at'])
                time_angle[time_str] = reading.get('wind_angle')

            values = [time_angle.get(t) if time_angle.get(t) is not None else float('nan') for t in labels]

            if not all(v != v for v in values):
                color = self.COLORS[i % len(self.COLORS)]
                ax.plot(
                    labels, values,
                    label=device_name,
                    color=color,
                    linewidth=1.5,
                    marker='o',
                    markersize=4
                )
                plotted_count += 1

        if plotted_count == 0:
            plt.close(fig)
            return None

        # Y-axis: 0-360 degrees with direction labels
        ax.set_ylim(0, 360)
        directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                      'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW', 'N']
        y_ticks = [i * 22.5 for i in range(17)]
        y_labels = ['{}° ({})'.format(int(y), directions[i]) for i, y in enumerate(y_ticks)]
        ax.set_yticks(y_ticks)
        ax.set_yticklabels(y_labels, fontsize=8)

        ax.set_ylabel('風向 (度)', fontsize=11)

        if len(labels) > 30:
            step = max(1, len(labels) // 20)
            ax.set_xticks([labels[i] for i in range(0, len(labels), step)])

        ax.tick_params(axis='x', rotation=45, labelsize=9)

        ax.legend(
            loc='upper center',
            bbox_to_anchor=(0.5, 1.15),
            ncol=min(plotted_count, 4),
            fontsize=9,
            frameon=False
        )

        plt.tight_layout()
        plt.subplots_adjust(top=0.85)

        filename = 'chart_wind_direction_{}.png'.format(date_str.replace('/', '-'))
        filepath = os.path.join(self.output_dir, filename)
        fig.savefig(filepath, dpi=self.dpi, bbox_inches='tight', facecolor='white')
        plt.close(fig)

        logging.info("Generated wind direction chart: %s", filepath)
        return filepath

    def generate_rain_chart(self, devices_data, date_str, interval_seconds=None):
        """
        Generate rain chart with 1h bar and 24h line.

        Args:
            devices_data: Dict of {device_name: sensor_data_list}
            date_str: Date string for title
            interval_seconds: Interval for downsampling

        Returns:
            str: Path to generated chart image
        """
        if not MATPLOTLIB_AVAILABLE:
            return None

        if interval_seconds and interval_seconds > 0:
            devices_data = {
                name: downsample_sensor_data(data, interval_seconds)
                for name, data in devices_data.items()
            }

        all_times = set()
        for data in devices_data.values():
            for reading in data:
                time_str = self._parse_time(reading['recorded_at'])
                all_times.add(time_str)

        labels = sorted(list(all_times))
        if not labels:
            return None

        title = '雨量 ({})'.format(date_str)
        fig, ax1 = self._setup_figure(title)
        ax2 = ax1.twinx()

        bar_color = 'rgba(54, 162, 235, 0.7)'
        line_color = '#FF6384'

        plotted_count = 0
        x_positions = range(len(labels))

        for device_name, data in devices_data.items():
            time_1h = {}
            time_24h = {}
            for reading in data:
                time_str = self._parse_time(reading['recorded_at'])
                time_1h[time_str] = reading.get('rain_1h')
                time_24h[time_str] = reading.get('rain_24h')

            # 1h rain as bar
            values_1h = [time_1h.get(t) if time_1h.get(t) is not None else 0 for t in labels]
            if any(v > 0 for v in values_1h):
                ax1.bar(
                    x_positions, values_1h,
                    label='{} (1h)'.format(device_name),
                    color='#36A2EB',
                    alpha=0.7,
                    width=0.8
                )
                plotted_count += 1

            # 24h rain as line
            values_24h = [time_24h.get(t) if time_24h.get(t) is not None else float('nan') for t in labels]
            if not all(v != v for v in values_24h):
                ax2.plot(
                    x_positions, values_24h,
                    label='{} (24h累計)'.format(device_name),
                    color=line_color,
                    linewidth=2,
                    marker='o',
                    markersize=4
                )
                plotted_count += 1

        if plotted_count == 0:
            plt.close(fig)
            return None

        ax1.set_ylabel('1h雨量 (mm)', fontsize=11, color='#36A2EB')
        ax2.set_ylabel('24h累計 (mm)', fontsize=11, color=line_color)

        ax1.set_ylim(bottom=0)
        ax2.set_ylim(bottom=0)

        ax1.set_xticks(list(x_positions))
        ax1.set_xticklabels(labels, rotation=45, fontsize=9)

        if len(labels) > 30:
            step = max(1, len(labels) // 20)
            visible_ticks = [i for i in range(0, len(labels), step)]
            ax1.set_xticks(visible_ticks)
            ax1.set_xticklabels([labels[i] for i in visible_ticks], rotation=45, fontsize=9)

        # Combined legend
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(
            lines1 + lines2, labels1 + labels2,
            loc='upper center',
            bbox_to_anchor=(0.5, 1.15),
            ncol=min(plotted_count, 4),
            fontsize=9,
            frameon=False
        )

        plt.tight_layout()
        plt.subplots_adjust(top=0.85)

        filename = 'chart_rain_{}.png'.format(date_str.replace('/', '-'))
        filepath = os.path.join(self.output_dir, filename)
        fig.savefig(filepath, dpi=self.dpi, bbox_inches='tight', facecolor='white')
        plt.close(fig)

        logging.info("Generated rain chart: %s", filepath)
        return filepath


class SlackImageUploader:
    """Upload images to Slack using the new API (files.getUploadURLExternal)."""

    def __init__(self, bot_token, channel_id):
        """
        Initialize Slack uploader.

        Args:
            bot_token: Slack Bot OAuth Token
            channel_id: Target Slack channel ID
        """
        self.bot_token = bot_token
        self.channel_id = channel_id

    def upload_file(self, file_path, title, initial_comment=''):
        """
        Upload a file to Slack using the new API.

        Uses the three-step upload process:
        1. files.getUploadURLExternal - get upload URL
        2. POST file to the upload URL
        3. files.completeUploadExternal - complete upload and share to channel

        Args:
            file_path: Path to the file to upload
            title: Title for the file
            initial_comment: Optional comment to post with the file

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.bot_token:
            logging.error("SLACK_BOT_TOKEN is not set")
            return False

        if not self.channel_id:
            logging.error("SLACK_CHANNEL_ID is not set")
            return False

        if not os.path.exists(file_path):
            logging.error("File not found: %s", file_path)
            return False

        headers = {
            'Authorization': 'Bearer {}'.format(self.bot_token)
        }

        file_size = os.path.getsize(file_path)
        filename = os.path.basename(file_path)

        # Step 1: Get upload URL
        try:
            response = requests.post(
                'https://slack.com/api/files.getUploadURLExternal',
                headers=headers,
                data={
                    'filename': filename,
                    'length': file_size
                },
                timeout=30
            )
            result = response.json()

            if not result.get('ok'):
                logging.error("files.getUploadURLExternal failed: %s", result.get('error'))
                return False

            upload_url = result['upload_url']
            file_id = result['file_id']

        except Exception as e:
            logging.error("Failed to get upload URL: %s", e)
            return False

        # Step 2: Upload file
        try:
            with open(file_path, 'rb') as f:
                response = requests.post(
                    upload_url,
                    files={'file': (filename, f)},
                    timeout=60
                )

            if response.status_code != 200:
                logging.error("File upload failed: %s", response.status_code)
                return False

        except Exception as e:
            logging.error("File upload failed: %s", e)
            return False

        # Step 3: Complete upload and share to channel
        try:
            response = requests.post(
                'https://slack.com/api/files.completeUploadExternal',
                headers={
                    'Authorization': 'Bearer {}'.format(self.bot_token),
                    'Content-Type': 'application/json'
                },
                json={
                    'files': [{'id': file_id, 'title': title}],
                    'channel_id': self.channel_id,
                    'initial_comment': initial_comment
                },
                timeout=30
            )
            result = response.json()

            if not result.get('ok'):
                logging.error("files.completeUploadExternal failed: %s", result.get('error'))
                return False

            logging.info("Slack upload successful: file_id=%s", file_id)
            return True

        except Exception as e:
            logging.error("Upload completion failed: %s", e)
            return False

    def upload_charts(self, chart_paths, date_str):
        """
        Upload multiple chart images to Slack.

        Args:
            chart_paths: Dict of {chart_type: file_path}
            date_str: Date string for comments

        Returns:
            dict: {chart_type: success_bool}
        """
        chart_titles = {
            'outdoor_temp': '屋外 温度',
            'outdoor_humidity': '屋外 湿度',
            'indoor_temp': '屋内 温度',
            'indoor_humidity': '屋内 湿度',
            'co2': 'CO2濃度',
            'pressure': '気圧',
            'noise': '騒音',
            'wind': '風速・突風',
            'wind_direction': '風向',
            'rain': '雨量',
        }

        chart_order = [
            'outdoor_temp', 'outdoor_humidity',
            'indoor_temp', 'indoor_humidity', 'co2',
            'pressure', 'noise',
            'wind', 'wind_direction',
            'rain'
        ]

        results = {}

        for chart_type in chart_order:
            if chart_type not in chart_paths or not chart_paths[chart_type]:
                continue

            file_path = chart_paths[chart_type]
            title = chart_titles.get(chart_type, chart_type)
            comment = '{} ({})'.format(title, date_str)

            success = self.upload_file(file_path, title, comment)
            results[chart_type] = success

            if success:
                # Clean up temporary file
                try:
                    os.remove(file_path)
                except Exception:
                    pass

        return results


def generate_and_upload_charts(
    outdoor_data, indoor_data, wind_data, rain_data,
    pressure_data, noise_data, date_str, interval_seconds,
    bot_token, channel_id
):
    """
    Generate all charts locally and upload to Slack.

    This is a convenience function that matches the workflow in main.py's send_graph_report().

    Args:
        outdoor_data: Dict of {device_name: sensor_data_list} for outdoor sensors
        indoor_data: Dict of {device_name: sensor_data_list} for indoor sensors
        wind_data: Dict of {device_name: sensor_data_list} for wind sensors
        rain_data: Dict of {device_name: sensor_data_list} for rain sensors
        pressure_data: Dict of {device_name: sensor_data_list} for pressure sensors
        noise_data: Dict of {device_name: sensor_data_list} for noise sensors
        date_str: Date string (e.g., '2024/01/30')
        interval_seconds: Interval for downsampling
        bot_token: Slack Bot OAuth Token
        channel_id: Slack channel ID

    Returns:
        dict: Results {chart_type: success_bool}
    """
    generator = LocalChartGenerator()
    uploader = SlackImageUploader(bot_token, channel_id)

    chart_paths = {}

    try:
        # Outdoor charts
        if outdoor_data:
            chart_paths['outdoor_temp'] = generator.generate_multi_device_chart(
                outdoor_data, 'temperature', date_str, interval_seconds=interval_seconds
            )
            chart_paths['outdoor_humidity'] = generator.generate_multi_device_chart(
                outdoor_data, 'humidity', date_str, interval_seconds=interval_seconds
            )

        # Indoor charts
        if indoor_data:
            chart_paths['indoor_temp'] = generator.generate_multi_device_chart(
                indoor_data, 'temperature', date_str, interval_seconds=interval_seconds
            )
            chart_paths['indoor_humidity'] = generator.generate_multi_device_chart(
                indoor_data, 'humidity', date_str, interval_seconds=interval_seconds
            )
            chart_paths['co2'] = generator.generate_multi_device_chart(
                indoor_data, 'co2', date_str, interval_seconds=interval_seconds
            )

        # Pressure chart
        if pressure_data:
            chart_paths['pressure'] = generator.generate_multi_device_chart(
                pressure_data, 'pressure', date_str, interval_seconds=interval_seconds
            )

        # Noise chart
        if noise_data:
            chart_paths['noise'] = generator.generate_multi_device_chart(
                noise_data, 'noise', date_str, interval_seconds=interval_seconds
            )

        # Wind charts
        if wind_data:
            chart_paths['wind'] = generator.generate_wind_chart(
                wind_data, date_str, interval_seconds=interval_seconds
            )
            chart_paths['wind_direction'] = generator.generate_wind_direction_chart(
                wind_data, date_str, interval_seconds=interval_seconds
            )

        # Rain chart
        if rain_data:
            chart_paths['rain'] = generator.generate_rain_chart(
                rain_data, date_str, interval_seconds=interval_seconds
            )

        # Upload to Slack
        results = uploader.upload_charts(chart_paths, date_str)
        return results

    except Exception as e:
        logging.error("Error in generate_and_upload_charts: %s", e)
        # Cleanup any generated files
        for path in chart_paths.values():
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
        return {}


if __name__ == '__main__':
    # Test chart generation
    logging.basicConfig(level=logging.DEBUG)

    generator = LocalChartGenerator()

    # Sample data
    test_data = {
        '[SB] Device1': [
            {'recorded_at': '2024-01-30T09:00:00', 'temperature': 22.5, 'humidity': 45, 'co2': 450},
            {'recorded_at': '2024-01-30T09:30:00', 'temperature': 23.0, 'humidity': 44, 'co2': 520},
            {'recorded_at': '2024-01-30T10:00:00', 'temperature': 23.5, 'humidity': 43, 'co2': 680},
            {'recorded_at': '2024-01-30T10:30:00', 'temperature': 24.0, 'humidity': 42, 'co2': 850},
            {'recorded_at': '2024-01-30T11:00:00', 'temperature': 24.5, 'humidity': 41, 'co2': 920},
        ],
        '[NA] Device2': [
            {'recorded_at': '2024-01-30T09:00:00', 'temperature': 21.0, 'humidity': 50, 'co2': 400},
            {'recorded_at': '2024-01-30T09:30:00', 'temperature': 21.5, 'humidity': 49, 'co2': 420},
            {'recorded_at': '2024-01-30T10:00:00', 'temperature': 22.0, 'humidity': 48, 'co2': 450},
            {'recorded_at': '2024-01-30T10:30:00', 'temperature': 22.5, 'humidity': 47, 'co2': 480},
            {'recorded_at': '2024-01-30T11:00:00', 'temperature': 23.0, 'humidity': 46, 'co2': 500},
        ],
    }

    chart_path = generator.generate_multi_device_chart(test_data, 'temperature', '2024-01-30')
    print("Generated chart: {}".format(chart_path))
