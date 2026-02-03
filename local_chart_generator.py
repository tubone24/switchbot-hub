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
        light_levels = [r['light_level'] for r in readings if r.get('light_level') is not None]

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
            'light_level': round(sum(light_levels) / len(light_levels)) if light_levels else None,
        })

    return result


def filter_data_by_hours(sensor_data, hours):
    """
    Filter sensor data to include only data from the last N hours.

    Args:
        sensor_data: List of sensor readings with 'recorded_at' key
        hours: Number of hours to include

    Returns:
        list: Filtered sensor data
    """
    if not sensor_data or hours <= 0:
        return sensor_data

    from datetime import timedelta
    cutoff = datetime.now() - timedelta(hours=hours)

    result = []
    for reading in sensor_data:
        timestamp = reading['recorded_at']
        try:
            if 'T' in timestamp:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                dt = dt.replace(tzinfo=None)
            else:
                dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')

            if dt >= cutoff:
                result.append(reading)
        except (ValueError, AttributeError):
            continue

    return result


def get_date_range_from_data(devices_data):
    """
    Get the date range (start and end dates) from device data.

    Args:
        devices_data: Dict of {device_name: sensor_data_list}

    Returns:
        tuple: (start_date_str, end_date_str) in YYYY/MM/DD format, or (None, None) if no data
    """
    all_timestamps = []

    for data in devices_data.values():
        for reading in data:
            timestamp = reading.get('recorded_at', '')
            try:
                if 'T' in timestamp:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    dt = dt.replace(tzinfo=None)
                else:
                    dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                all_timestamps.append(dt)
            except (ValueError, AttributeError):
                continue

    if not all_timestamps:
        return None, None

    min_dt = min(all_timestamps)
    max_dt = max(all_timestamps)

    return min_dt.strftime('%Y/%m/%d'), max_dt.strftime('%Y/%m/%d')


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
        """Parse timestamp and return datetime object."""
        try:
            if 'T' in timestamp:
                # ISO format: 2024-01-30T09:02:00
                return datetime.strptime(timestamp[:19], '%Y-%m-%dT%H:%M:%S')
            else:
                # Space format: 2024-01-30 09:02:00
                return datetime.strptime(timestamp[:19], '%Y-%m-%d %H:%M:%S')
        except (ValueError, IndexError):
            # Fallback: try to parse just time part
            try:
                time_str = timestamp.split('T')[1][:5] if 'T' in timestamp else timestamp[11:16]
                return datetime.strptime(time_str, '%H:%M')
            except:
                return datetime.now()

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

    def _setup_xaxis_ticks(self, ax, hours_range=None):
        """Setup X-axis date formatting based on hours_range."""
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        if hours_range == 12:
            # 12-hour chart: ticks every 30 minutes
            ax.xaxis.set_major_locator(mdates.MinuteLocator(byminute=[0, 30]))
        elif hours_range == 24:
            # 24-hour chart: ticks every 1 hour
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        else:
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())

    def generate_multi_device_chart(self, devices_data, metric, date_str, interval_seconds=None, hours_range=None, chart_type=None):
        """
        Generate chart comparing multiple devices.

        Args:
            devices_data: Dict of {device_name: sensor_data_list}
            metric: Metric to compare ('temperature', 'humidity', 'co2', etc.)
            date_str: Date string for title
            interval_seconds: Interval for downsampling
            hours_range: Number of hours to include (e.g., 12 or 24). None for all data.
            chart_type: Optional chart type identifier for unique filename (e.g., 'outdoor', 'indoor')

        Returns:
            str: Path to generated chart image
        """
        if not MATPLOTLIB_AVAILABLE:
            return None

        # Filter by time range if specified
        if hours_range and hours_range > 0:
            devices_data = {
                name: filter_data_by_hours(data, hours_range)
                for name, data in devices_data.items()
            }

        # Downsample if needed
        if interval_seconds and interval_seconds > 0:
            devices_data = {
                name: downsample_sensor_data(data, interval_seconds)
                for name, data in devices_data.items()
            }

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
            'rain_24h': '雨量/24h (mm)',
            'light_level': '照度'
        }

        # Build title with time range and date range
        time_range_str = '直近{}h'.format(hours_range) if hours_range else date_str
        start_date, end_date = get_date_range_from_data(devices_data)
        if start_date and end_date:
            if start_date == end_date:
                date_range_str = start_date
            else:
                date_range_str = '{}〜{}'.format(start_date, end_date)
            title = '{} ({}) {}'.format(metric_labels.get(metric, metric), time_range_str, date_range_str)
        else:
            title = '{} ({})'.format(metric_labels.get(metric, metric), time_range_str)
        fig, ax = self._setup_figure(title)

        # Plot each device with its own time series (to avoid gaps from mismatched timestamps)
        plotted_count = 0
        for i, (device_name, data) in enumerate(devices_data.items()):
            # Build time-value pairs for this device only
            device_times = []
            device_values = []

            for reading in data:
                time_dt = self._parse_time(reading['recorded_at'])
                value = reading.get(metric)
                if value is not None:
                    if needs_wind_conversion:
                        value = round(value / 3.6, 1)
                    device_times.append(time_dt)
                    device_values.append(value)

            # Skip if no valid data
            if not device_values:
                continue

            color = self.COLORS[i % len(self.COLORS)]

            ax.plot(
                device_times, device_values,
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

        # Set X-axis date formatting
        self._setup_xaxis_ticks(ax, hours_range)
        ax.tick_params(axis='x', rotation=45, labelsize=9)
        ax.tick_params(axis='y', labelsize=10)

        # Legend at bottom
        ax.legend(
            loc='upper center',
            bbox_to_anchor=(0.5, -0.15),
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
        plt.subplots_adjust(bottom=0.2)

        # Save to file
        hours_suffix = '_{}h'.format(hours_range) if hours_range else ''
        type_prefix = '{}_'.format(chart_type) if chart_type else ''
        filename = 'chart_{}{}{}_{}.png'.format(type_prefix, metric, hours_suffix, date_str.replace('/', '-'))
        filepath = os.path.join(self.output_dir, filename)
        fig.savefig(filepath, dpi=self.dpi, bbox_inches='tight', facecolor='white')
        plt.close(fig)

        logging.info("Generated chart: %s", filepath)
        return filepath

    def generate_wind_chart(self, devices_data, date_str, interval_seconds=None, hours_range=None):
        """
        Generate wind chart with speed and gust.

        Args:
            devices_data: Dict of {device_name: sensor_data_list}
            date_str: Date string for title
            interval_seconds: Interval for downsampling
            hours_range: Number of hours to include (e.g., 12 or 24). None for all data.

        Returns:
            str: Path to generated chart image
        """
        if not MATPLOTLIB_AVAILABLE:
            return None

        # Filter by time range if specified
        if hours_range and hours_range > 0:
            devices_data = {
                name: filter_data_by_hours(data, hours_range)
                for name, data in devices_data.items()
            }

        # Downsample if needed
        if interval_seconds and interval_seconds > 0:
            devices_data = {
                name: downsample_sensor_data(data, interval_seconds)
                for name, data in devices_data.items()
            }

        time_range_str = '直近{}h'.format(hours_range) if hours_range else date_str
        start_date, end_date = get_date_range_from_data(devices_data)
        if start_date and end_date:
            if start_date == end_date:
                date_range_str = start_date
            else:
                date_range_str = '{}〜{}'.format(start_date, end_date)
            title = '風速 ({}) {}'.format(time_range_str, date_range_str)
        else:
            title = '風速 ({})'.format(time_range_str)
        fig, ax = self._setup_figure(title)

        wind_color = '#36A2EB'  # Blue
        gust_color = '#FF6384'  # Red

        plotted_count = 0

        for device_name, data in devices_data.items():
            # Build time-value pairs for wind and gust
            wind_times = []
            wind_values = []
            gust_times = []
            gust_values = []

            for reading in data:
                time_dt = self._parse_time(reading['recorded_at'])
                wind_kmh = reading.get('wind_strength')
                gust_kmh = reading.get('gust_strength')

                if wind_kmh is not None:
                    wind_times.append(time_dt)
                    wind_values.append(round(wind_kmh / 3.6, 1))

                if gust_kmh is not None:
                    gust_times.append(time_dt)
                    gust_values.append(round(gust_kmh / 3.6, 1))

            # Wind speed
            if wind_values:
                ax.plot(
                    wind_times, wind_values,
                    label='{} 風速'.format(device_name),
                    color=wind_color,
                    linewidth=1.5,
                    marker='o',
                    markersize=4
                )
                ax.fill_between(wind_times, wind_values, alpha=0.1, color=wind_color)
                plotted_count += 1

            # Gust speed
            if gust_values:
                ax.plot(
                    gust_times, gust_values,
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

        # Set X-axis date formatting
        self._setup_xaxis_ticks(ax, hours_range)
        ax.tick_params(axis='x', rotation=45, labelsize=9)

        ax.legend(
            loc='upper center',
            bbox_to_anchor=(0.5, -0.15),
            ncol=min(plotted_count, 4),
            fontsize=9,
            frameon=False
        )

        plt.tight_layout()
        plt.subplots_adjust(bottom=0.2)

        hours_suffix = '_{}h'.format(hours_range) if hours_range else ''
        filename = 'chart_wind{}_{}.png'.format(hours_suffix, date_str.replace('/', '-'))
        filepath = os.path.join(self.output_dir, filename)
        fig.savefig(filepath, dpi=self.dpi, bbox_inches='tight', facecolor='white')
        plt.close(fig)

        logging.info("Generated wind chart: %s", filepath)
        return filepath

    def generate_wind_direction_chart(self, devices_data, date_str, interval_seconds=None, hours_range=None):
        """
        Generate wind direction chart.

        Args:
            devices_data: Dict of {device_name: sensor_data_list}
            date_str: Date string for title
            interval_seconds: Interval for downsampling
            hours_range: Number of hours to include (e.g., 12 or 24). None for all data.

        Returns:
            str: Path to generated chart image
        """
        if not MATPLOTLIB_AVAILABLE:
            return None

        # Filter by time range if specified
        if hours_range and hours_range > 0:
            devices_data = {
                name: filter_data_by_hours(data, hours_range)
                for name, data in devices_data.items()
            }

        if interval_seconds and interval_seconds > 0:
            devices_data = {
                name: downsample_sensor_data(data, interval_seconds)
                for name, data in devices_data.items()
            }

        time_range_str = '直近{}h'.format(hours_range) if hours_range else date_str
        start_date, end_date = get_date_range_from_data(devices_data)
        if start_date and end_date:
            if start_date == end_date:
                date_range_str = start_date
            else:
                date_range_str = '{}〜{}'.format(start_date, end_date)
            title = '風向 ({}) {}'.format(time_range_str, date_range_str)
        else:
            title = '風向 ({})'.format(time_range_str)
        fig, ax = self._setup_figure(title)

        plotted_count = 0

        for i, (device_name, data) in enumerate(devices_data.items()):
            # Build time-value pairs for this device
            device_times = []
            device_values = []

            for reading in data:
                time_dt = self._parse_time(reading['recorded_at'])
                angle = reading.get('wind_angle')
                if angle is not None:
                    device_times.append(time_dt)
                    device_values.append(angle)

            if not device_values:
                continue

            color = self.COLORS[i % len(self.COLORS)]
            ax.plot(
                device_times, device_values,
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

        # Set X-axis date formatting
        self._setup_xaxis_ticks(ax, hours_range)
        ax.tick_params(axis='x', rotation=45, labelsize=9)

        ax.legend(
            loc='upper center',
            bbox_to_anchor=(0.5, -0.15),
            ncol=min(plotted_count, 4),
            fontsize=9,
            frameon=False
        )

        plt.tight_layout()
        plt.subplots_adjust(bottom=0.2)

        hours_suffix = '_{}h'.format(hours_range) if hours_range else ''
        filename = 'chart_wind_direction{}_{}.png'.format(hours_suffix, date_str.replace('/', '-'))
        filepath = os.path.join(self.output_dir, filename)
        fig.savefig(filepath, dpi=self.dpi, bbox_inches='tight', facecolor='white')
        plt.close(fig)

        logging.info("Generated wind direction chart: %s", filepath)
        return filepath

    def generate_rain_chart(self, devices_data, date_str, interval_seconds=None, hours_range=None):
        """
        Generate rain chart with 1h bar and 24h line.

        Args:
            devices_data: Dict of {device_name: sensor_data_list}
            date_str: Date string for title
            interval_seconds: Interval for downsampling
            hours_range: Number of hours to include (e.g., 12 or 24). None for all data.

        Returns:
            str: Path to generated chart image
        """
        if not MATPLOTLIB_AVAILABLE:
            return None

        # Filter by time range if specified
        if hours_range and hours_range > 0:
            devices_data = {
                name: filter_data_by_hours(data, hours_range)
                for name, data in devices_data.items()
            }

        if interval_seconds and interval_seconds > 0:
            devices_data = {
                name: downsample_sensor_data(data, interval_seconds)
                for name, data in devices_data.items()
            }

        all_times = set()
        for data in devices_data.values():
            for reading in data:
                time_dt = self._parse_time(reading['recorded_at'])
                all_times.add(time_dt)

        time_list = sorted(list(all_times))
        if not time_list:
            return None

        time_range_str = '直近{}h'.format(hours_range) if hours_range else date_str
        start_date, end_date = get_date_range_from_data(devices_data)
        if start_date and end_date:
            if start_date == end_date:
                date_range_str = start_date
            else:
                date_range_str = '{}〜{}'.format(start_date, end_date)
            title = '雨量 ({}) {}'.format(time_range_str, date_range_str)
        else:
            title = '雨量 ({})'.format(time_range_str)
        fig, ax1 = self._setup_figure(title)
        ax2 = ax1.twinx()

        line_color = '#FF6384'

        plotted_count = 0
        # Convert datetime to matplotlib date numbers for bar chart
        x_positions = mdates.date2num(time_list)
        # Calculate bar width based on data interval (assume 10 minutes minimum)
        if len(x_positions) > 1:
            bar_width = (x_positions[-1] - x_positions[0]) / len(x_positions) * 0.8
        else:
            bar_width = 1 / 144  # 10 minutes in days

        for device_name, data in devices_data.items():
            time_1h = {}
            time_24h = {}
            for reading in data:
                time_dt = self._parse_time(reading['recorded_at'])
                time_1h[time_dt] = reading.get('rain_1h')
                time_24h[time_dt] = reading.get('rain_24h')

            # 1h rain as bar
            values_1h = [time_1h.get(t) if time_1h.get(t) is not None else 0 for t in time_list]
            if any(v > 0 for v in values_1h):
                ax1.bar(
                    x_positions, values_1h,
                    label='{} (1h)'.format(device_name),
                    color='#36A2EB',
                    alpha=0.7,
                    width=bar_width
                )
                plotted_count += 1

            # 24h rain as line
            values_24h = [time_24h.get(t) if time_24h.get(t) is not None else float('nan') for t in time_list]
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

        # Set X-axis date formatting
        self._setup_xaxis_ticks(ax1, hours_range)
        ax1.tick_params(axis='x', rotation=45, labelsize=9)

        # Combined legend at bottom
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(
            lines1 + lines2, labels1 + labels2,
            loc='upper center',
            bbox_to_anchor=(0.5, -0.15),
            ncol=min(plotted_count, 4),
            fontsize=9,
            frameon=False
        )

        plt.tight_layout()
        plt.subplots_adjust(bottom=0.2)

        hours_suffix = '_{}h'.format(hours_range) if hours_range else ''
        filename = 'chart_rain{}_{}.png'.format(hours_suffix, date_str.replace('/', '-'))
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

    def post_message(self, text):
        """
        Post a text message to Slack channel.

        Args:
            text: Message text

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.bot_token or not self.channel_id:
            return False

        try:
            response = requests.post(
                'https://slack.com/api/chat.postMessage',
                headers={
                    'Authorization': 'Bearer {}'.format(self.bot_token),
                    'Content-Type': 'application/json'
                },
                json={
                    'channel': self.channel_id,
                    'text': text
                },
                timeout=30
            )
            result = response.json()
            return result.get('ok', False)
        except Exception as e:
            logging.error("Failed to post message: %s", e)
            return False

    def upload_charts(self, chart_paths, date_str):
        """
        Upload multiple chart images to Slack.
        Supports both regular keys (e.g., 'outdoor_temp') and time-suffixed keys (e.g., 'outdoor_temp_12h').

        Args:
            chart_paths: Dict of {chart_type: file_path} or {chart_type_Nh: file_path}
            date_str: Date string for comments

        Returns:
            dict: {chart_type: success_bool}
        """
        chart_titles = {
            'outdoor_temp': '🌳 屋外 温度',
            'outdoor_humidity': '🌳 屋外 湿度',
            'indoor_temp': '🏠 屋内 温度',
            'indoor_humidity': '🏠 屋内 湿度',
            'co2': '🏠 CO2濃度',
            'pressure': '🏠 気圧',
            'noise': '🏠 騒音',
            'wind': '🌬️ 風速・突風',
            'wind_direction': '🧭 風向',
            'rain': '🌧️ 雨量',
            'light_level': '💡 照度',
        }

        # Order: 12h charts first, then 24h charts (grouped by metric type)
        chart_order = [
            # 12h charts
            'outdoor_temp_12h', 'outdoor_humidity_12h',
            'indoor_temp_12h', 'indoor_humidity_12h', 'co2_12h',
            'pressure_12h', 'noise_12h',
            'wind_12h', 'wind_direction_12h',
            'rain_12h', 'light_level_12h',
            # 24h charts
            'outdoor_temp_24h', 'outdoor_humidity_24h',
            'indoor_temp_24h', 'indoor_humidity_24h', 'co2_24h',
            'pressure_24h', 'noise_24h',
            'wind_24h', 'wind_direction_24h',
            'rain_24h', 'light_level_24h',
            # Legacy keys (without time suffix)
            'outdoor_temp', 'outdoor_humidity',
            'indoor_temp', 'indoor_humidity', 'co2',
            'pressure', 'noise',
            'wind', 'wind_direction',
            'rain', 'light_level'
        ]

        results = {}

        for chart_key in chart_order:
            if chart_key not in chart_paths or not chart_paths[chart_key]:
                continue

            file_path = chart_paths[chart_key]

            # Extract base chart type and time suffix
            if chart_key.endswith('_12h'):
                base_type = chart_key[:-4]
                time_suffix = ' (直近12h)'
            elif chart_key.endswith('_24h'):
                base_type = chart_key[:-4]
                time_suffix = ' (直近24h)'
            else:
                base_type = chart_key
                time_suffix = ''

            title = chart_titles.get(base_type, base_type) + time_suffix
            comment = '{}'.format(title)

            success = self.upload_file(file_path, title, comment)
            results[chart_key] = success

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
                outdoor_data, 'temperature', date_str, interval_seconds=interval_seconds,
                chart_type='outdoor'
            )
            chart_paths['outdoor_humidity'] = generator.generate_multi_device_chart(
                outdoor_data, 'humidity', date_str, interval_seconds=interval_seconds,
                chart_type='outdoor'
            )

        # Indoor charts
        if indoor_data:
            chart_paths['indoor_temp'] = generator.generate_multi_device_chart(
                indoor_data, 'temperature', date_str, interval_seconds=interval_seconds,
                chart_type='indoor'
            )
            chart_paths['indoor_humidity'] = generator.generate_multi_device_chart(
                indoor_data, 'humidity', date_str, interval_seconds=interval_seconds,
                chart_type='indoor'
            )
            chart_paths['co2'] = generator.generate_multi_device_chart(
                indoor_data, 'co2', date_str, interval_seconds=interval_seconds,
                chart_type='indoor'
            )

        # Pressure chart
        if pressure_data:
            chart_paths['pressure'] = generator.generate_multi_device_chart(
                pressure_data, 'pressure', date_str, interval_seconds=interval_seconds,
                chart_type='pressure'
            )

        # Noise chart
        if noise_data:
            chart_paths['noise'] = generator.generate_multi_device_chart(
                noise_data, 'noise', date_str, interval_seconds=interval_seconds,
                chart_type='noise'
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
