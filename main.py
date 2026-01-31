#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SwitchBot Device Monitor
Monitors SwitchBot devices via polling and webhooks, sends Slack notifications.

Python 3.7+ compatible, requires only requests library.
"""
import json
import os
import sys
import time
import signal
import logging
from datetime import datetime

from switchbot_api import SwitchBotAPI
from netatmo_api import NetatmoAPI
from google_nest_api import GoogleNestAPI
from database import DeviceDatabase
from slack_notifier import SlackNotifier
from webhook_server import WebhookServer, parse_webhook_event
from cloudflare_tunnel import CloudflareTunnel
from chart_generator import ChartGenerator

# Optional: Local chart generator for Raspberry Pi (requires matplotlib)
try:
    from local_chart_generator import LocalChartGenerator, SlackImageUploader
    LOCAL_CHART_AVAILABLE = True
except ImportError:
    LOCAL_CHART_AVAILABLE = False


# Global flag for graceful shutdown
running = True


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global running
    logging.info("Received signal %s, shutting down...", signum)
    running = False


def setup_logging(log_level='INFO', log_file=None):
    """Setup logging configuration."""
    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers
    )


def load_config(config_path):
    """Load configuration from JSON file."""
    if not os.path.exists(config_path):
        logging.error("Config file not found: %s", config_path)
        logging.error("Please copy config.json.example to config.json and configure it")
        sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def matches_filter(device_name, filter_list):
    """
    Check if device name matches any filter pattern.

    Args:
        device_name: Device name to check
        filter_list: List of filter patterns (partial match)

    Returns:
        bool: True if matches any filter
    """
    for pattern in filter_list:
        if pattern in device_name:
            return True
    return False


def build_device_map(api, config):
    """
    Build device mapping with categories.

    Args:
        api: SwitchBotAPI instance
        config: Configuration dict

    Returns:
        dict: {device_id: {info, category}}
              category: 'ignore', 'polling', 'webhook'
    """
    devices_data = api.get_devices()
    device_list = devices_data.get('deviceList', [])

    ignore_patterns = config.get('monitor', {}).get('ignore_devices', [])
    polling_patterns = config.get('monitor', {}).get('polling_devices', [])

    device_map = {}

    for device in device_list:
        device_id = device.get('deviceId')
        device_name = device.get('deviceName', 'Unknown')
        device_type = device.get('deviceType', 'Unknown')

        # Determine category
        if matches_filter(device_name, ignore_patterns):
            category = 'ignore'
        elif matches_filter(device_name, polling_patterns):
            category = 'polling'
        else:
            category = 'webhook'

        device_map[device_id] = {
            'device_id': device_id,
            'device_name': device_name,
            'device_type': device_type,
            'category': category
        }

        logging.info("Device: %s (%s) -> %s", device_name, device_type, category)

    return device_map


class SwitchBotMonitor:
    """Main monitor class integrating all components."""

    def __init__(self, config):
        """Initialize monitor with configuration."""
        self.config = config

        # Initialize SwitchBot API
        switchbot_config = config['switchbot']
        self.api = SwitchBotAPI(
            token=switchbot_config['token'],
            secret=switchbot_config['secret']
        )

        # Initialize Netatmo API (optional)
        self.netatmo_api = None
        netatmo_config = config.get('netatmo', {})
        if netatmo_config.get('enabled', False):
            try:
                self.netatmo_api = NetatmoAPI(
                    client_id=netatmo_config['client_id'],
                    client_secret=netatmo_config['client_secret'],
                    refresh_token=netatmo_config['refresh_token'],
                    credentials_file=netatmo_config.get('credentials_file')
                )
                logging.info("Netatmo API initialized")
            except Exception as e:
                logging.error("Failed to initialize Netatmo API: %s", e)

        # Initialize Google Nest API (optional)
        self.nest_api = None
        nest_config = config.get('google_nest', {})
        if nest_config.get('enabled', False):
            try:
                self.nest_api = GoogleNestAPI(
                    project_id=nest_config['project_id'],
                    client_id=nest_config['client_id'],
                    client_secret=nest_config['client_secret'],
                    refresh_token=nest_config['refresh_token'],
                    credentials_file=nest_config.get('credentials_file')
                )
                logging.info("Google Nest API initialized")
            except Exception as e:
                logging.error("Failed to initialize Google Nest API: %s", e)

        # Initialize database
        db_path = config.get('database', {}).get('path', 'device_states.db')
        self.db = DeviceDatabase(db_path)

        # Initialize Slack with new multi-channel config
        slack_config = config.get('slack', {})
        self.slack = SlackNotifier(slack_config)

        # Device map
        self.device_map = {}

        # Webhook server
        self.webhook_server = None
        self.tunnel = None
        self.webhook_url = None

        # Chart generator
        self.chart_generator = ChartGenerator()

        # Local chart generator (for Raspberry Pi with matplotlib)
        graph_config = config.get('graph_report', {})
        self.use_local_chart = graph_config.get('use_local_chart', False)
        self.local_chart_generator = None
        self.slack_uploader = None

        if self.use_local_chart:
            if LOCAL_CHART_AVAILABLE:
                self.local_chart_generator = LocalChartGenerator()
                bot_token = slack_config.get('bot_token')
                channel_id = slack_config.get('channels', {}).get('atmos_graph')
                if bot_token and channel_id:
                    self.slack_uploader = SlackImageUploader(bot_token, channel_id)
                    logging.info("Local chart generator enabled (matplotlib + Slack file upload)")
                else:
                    logging.warning("Local chart enabled but bot_token or channel_id missing, falling back to URL mode")
                    self.use_local_chart = False
            else:
                logging.warning("Local chart enabled but matplotlib not available, falling back to URL mode")
                self.use_local_chart = False

        # Graph report tracking (5-minute interval)
        self.last_graph_report = 0

        # Netatmo polling tracking (separate interval)
        self.last_netatmo_poll = 0

        # Google Nest polling tracking
        self.last_nest_poll = 0
        self.nest_device_states = {}  # Track device connectivity states

        # Outdoor alert tracking (to avoid duplicate alerts)
        self.last_alerts = {
            'rain': {},        # {device_id: last_alert_time}
            'wind': {},        # {device_id: last_alert_time}
            'temperature': {}, # {device_id: last_alert_time}
            'pressure': {},    # {device_id: last_alert_time}
        }
        # Minimum interval between same type alerts (seconds)
        self.alert_cooldown = 3600  # 1 hour

    def setup_webhook_server(self):
        """Setup webhook server and Cloudflare tunnel."""
        webhook_config = self.config.get('webhook', {})
        tunnel_config = self.config.get('cloudflare_tunnel', {})

        if not webhook_config.get('enabled', False):
            logging.info("Webhook server disabled")
            return False

        port = webhook_config.get('port', 8080)
        path = webhook_config.get('path', '/switchbot/webhook')

        # Start webhook server
        self.webhook_server = WebhookServer(
            port=port,
            path=path,
            callback=self.handle_webhook_event
        )
        self.webhook_server.start()

        # Start Cloudflare tunnel if enabled
        if tunnel_config.get('enabled', False):
            self.tunnel = CloudflareTunnel(
                local_port=port,
                hostname=tunnel_config.get('hostname'),
                config_path=tunnel_config.get('config_path')
            )

            if self.tunnel.start():
                # Wait for URL to be available
                for _ in range(10):
                    if self.tunnel.public_url:
                        break
                    time.sleep(1)

                self.webhook_url = self.tunnel.get_webhook_url(path)
                logging.info("Webhook URL: %s", self.webhook_url)
            else:
                logging.error("Failed to start Cloudflare tunnel")
                return False
        else:
            logging.info("Cloudflare tunnel disabled, using local server only")
            self.webhook_url = self.webhook_server.get_local_url()

        return True

    def cleanup_old_webhooks(self):
        """
        Remove all existing webhooks from SwitchBot.
        Called on startup to clean up old Quick Tunnel URLs.
        """
        try:
            current = self.api.query_webhook()
            urls = current.get('urls', [])

            if not urls:
                logging.info("No existing webhooks to clean up")
                return True

            logging.info("Found %d existing webhook(s) to clean up", len(urls))

            for url in urls:
                try:
                    self.api.delete_webhook(url)
                    logging.info("Deleted old webhook: %s", url)
                except Exception as e:
                    logging.warning("Failed to delete webhook %s: %s", url, e)

            return True
        except Exception as e:
            logging.warning("Failed to query webhooks for cleanup: %s", e)
            return False

    def register_webhook(self):
        """Register webhook URL with SwitchBot API."""
        if not self.webhook_url:
            logging.warning("No webhook URL available")
            return False

        # First, clean up any old webhooks (important for Quick Tunnel)
        # Quick Tunnel generates new URLs on each restart
        self.cleanup_old_webhooks()

        # Register new webhook
        try:
            self.api.setup_webhook(self.webhook_url)
            logging.info("Webhook registered: %s", self.webhook_url)
            return True
        except Exception as e:
            logging.error("Failed to register webhook: %s", e)
            return False

    def handle_webhook_event(self, event_data):
        """
        Handle incoming webhook event.

        Args:
            event_data: Raw event data from SwitchBot
        """
        try:
            parsed = parse_webhook_event(event_data)
            device_mac = parsed['device_mac']

            # Find device by MAC (device IDs in webhook are MAC addresses)
            device_info = None
            for dev_id, info in self.device_map.items():
                # MAC might be part of device ID or match directly
                if device_mac and (device_mac in dev_id or dev_id.endswith(device_mac)):
                    device_info = info
                    break

            if not device_info:
                logging.debug("Webhook for unknown device MAC: %s", device_mac)
                # Still process it, might be useful
                device_info = {
                    'device_id': device_mac,
                    'device_name': 'Unknown ({})'.format(parsed['device_type']),
                    'device_type': parsed['device_type'],
                    'category': 'webhook'
                }

            device_id = device_info['device_id']
            device_name = device_info['device_name']
            device_type = device_info['device_type']
            status = parsed['status']

            logging.info(
                "[Webhook] Device: %s (%s), Status: %s",
                device_name, device_type, status
            )

            # Get previous state
            previous = self.db.get_device_state(device_id)
            previous_status = previous['status'] if previous else None

            # Save new state
            changed = self.db.save_device_state(
                device_id,
                device_name,
                device_type,
                status
            )

            # Save sensor data if it's an atmosphere sensor (for graphs)
            if self._is_sensor_device(device_type):
                self.db.save_sensor_data(device_id, device_name, status)
                logging.debug("Saved webhook sensor data for %s", device_name)

            # Send notification based on device category
            if changed:
                category = self.slack.get_device_category(device_type)

                if category == 'security':
                    # Security notification to #home-security
                    self.slack.notify_security_event(device_name, device_type, status)
                elif category == 'atmos':
                    # Atmosphere notification to #atmos-update
                    self.slack.notify_atmos_update(device_name, device_type, status)
                else:
                    # Other devices - log only for now
                    logging.info("Device %s changed but no notification channel configured", device_name)

        except Exception as e:
            logging.error("Error handling webhook event: %s", e)

    def poll_devices(self):
        """Poll devices marked for polling."""
        polling_devices = [
            info for info in self.device_map.values()
            if info['category'] == 'polling'
        ]

        if not polling_devices:
            logging.debug("No devices configured for polling")
            return

        logging.info("Polling %d devices...", len(polling_devices))

        for device_info in polling_devices:
            device_id = device_info['device_id']
            device_name = device_info['device_name']
            device_type = device_info['device_type']

            try:
                status = self.api.get_device_status(device_id)

                # Get previous state
                previous = self.db.get_device_state(device_id)
                previous_status = previous['status'] if previous else None

                # Save new state
                changed = self.db.save_device_state(
                    device_id, device_name, device_type, status
                )

                # Always save sensor time series data (for temperature/humidity/CO2 sensors)
                if self._is_sensor_device(device_type):
                    self.db.save_sensor_data(device_id, device_name, status)
                    logging.debug("Saved sensor data for %s", device_name)

                # Note: For polling devices, we don't send individual notifications
                # The data is collected for the periodic graph report
                if changed:
                    logging.info(
                        "[Polling] Device %s: temp=%.1f, humidity=%d, CO2=%s",
                        device_name,
                        status.get('temperature', 0),
                        status.get('humidity', 0),
                        status.get('CO2', 'N/A')
                    )

            except Exception as e:
                logging.error("Error polling %s: %s", device_name, e)
                if self.config.get('slack', {}).get('notify_errors', False):
                    self.slack.notify_error(str(e), device_name)

    def poll_netatmo(self):
        """Poll Netatmo weather station for sensor data."""
        if not self.netatmo_api:
            return

        logging.info("Polling Netatmo weather station...")

        try:
            readings = self.netatmo_api.get_all_sensor_readings()

            for reading in readings:
                device_id = reading['device_id']
                device_name = reading['device_name']
                station_name = reading.get('station_name', '')
                module_type = reading.get('module_type', '')
                is_outdoor = reading.get('is_outdoor', False)

                # Save to database
                saved = self.db.save_netatmo_data(
                    device_id=device_id,
                    device_name=device_name,
                    station_name=station_name,
                    module_type=module_type,
                    is_outdoor=is_outdoor,
                    temperature=reading.get('temperature'),
                    humidity=reading.get('humidity'),
                    co2=reading.get('co2'),
                    pressure=reading.get('pressure'),
                    noise=reading.get('noise'),
                    wind_strength=reading.get('wind_strength'),
                    wind_angle=reading.get('wind_angle'),
                    gust_strength=reading.get('gust_strength'),
                    gust_angle=reading.get('gust_angle'),
                    rain=reading.get('rain'),
                    rain_1h=reading.get('rain_1h'),
                    rain_24h=reading.get('rain_24h'),
                    battery_percent=reading.get('battery_percent')
                )

                if saved:
                    location = "屋外" if is_outdoor else "屋内"
                    parts = []
                    if reading.get('temperature') is not None:
                        parts.append("temp={:.1f}".format(reading['temperature']))
                    if reading.get('humidity') is not None:
                        parts.append("humidity={}".format(reading['humidity']))
                    if reading.get('co2') is not None:
                        parts.append("CO2={}".format(reading['co2']))
                    if reading.get('pressure') is not None:
                        parts.append("pressure={:.1f}".format(reading['pressure']))
                    if reading.get('noise') is not None:
                        parts.append("noise={}".format(reading['noise']))
                    if reading.get('wind_strength') is not None:
                        parts.append("wind={}km/h".format(reading['wind_strength']))
                    if reading.get('gust_strength') is not None:
                        parts.append("gust={}km/h".format(reading['gust_strength']))
                    if reading.get('wind_angle') is not None:
                        parts.append("dir={}°".format(reading['wind_angle']))
                    if reading.get('rain') is not None:
                        parts.append("rain={}mm".format(reading['rain']))
                    if reading.get('rain_1h') is not None:
                        parts.append("rain1h={}mm".format(reading['rain_1h']))
                    if reading.get('rain_24h') is not None:
                        parts.append("rain24h={}mm".format(reading['rain_24h']))

                    logging.info(
                        "[Netatmo] %s (%s/%s): %s",
                        device_name, station_name, location, ", ".join(parts)
                    )

                    # Send Slack notification to #atmos-update
                    self.slack.notify_netatmo_update(
                        device_name, module_type, is_outdoor, reading
                    )

            logging.info("Netatmo polling complete: %d readings", len(readings))

            # Check for outdoor alerts after polling
            self.check_outdoor_alerts()

        except Exception as e:
            logging.error("Error polling Netatmo: %s", e)
            if self.config.get('slack', {}).get('notify_errors', False):
                self.slack.notify_error("Netatmo: {}".format(str(e)))

    def poll_nest(self):
        """Poll Google Nest devices for status updates."""
        if not self.nest_api:
            return

        logging.info("Polling Google Nest devices...")

        try:
            devices = self.nest_api.poll_all_devices()

            for device in devices:
                device_id = device.get('device_id')
                device_name = device.get('device_name', 'Unknown')
                device_type = 'Doorbell' if device.get('is_doorbell') else 'Camera'
                connectivity = device.get('connectivity_status', 'UNKNOWN')
                online = device.get('online', True)

                # Get previous state
                prev_state = self.nest_device_states.get(device_id, {})
                prev_connectivity = prev_state.get('connectivity_status')

                # Save current state
                self.nest_device_states[device_id] = {
                    'device_name': device_name,
                    'device_type': device_type,
                    'connectivity_status': connectivity,
                    'online': online,
                    'is_doorbell': device.get('is_doorbell', False),
                    'has_motion': device.get('has_motion', False),
                    'has_person': device.get('has_person', False),
                }

                # Log status
                if device.get('error'):
                    logging.warning(
                        "[Nest] %s: Error - %s",
                        device_name, device.get('error')
                    )
                else:
                    logging.info(
                        "[Nest] %s (%s): connectivity=%s, motion=%s, person=%s",
                        device_name, device_type, connectivity,
                        device.get('has_motion'), device.get('has_person')
                    )

                # Check for connectivity changes
                if prev_connectivity and prev_connectivity != connectivity:
                    logging.info(
                        "[Nest] %s connectivity changed: %s -> %s",
                        device_name, prev_connectivity, connectivity
                    )
                    self.slack.notify_nest_device_status(
                        device_name, device_type, device
                    )

            logging.info("Google Nest polling complete: %d devices", len(devices))

        except Exception as e:
            logging.error("Error polling Google Nest: %s", e)
            if self.config.get('slack', {}).get('notify_errors', False):
                self.slack.notify_error("Google Nest: {}".format(str(e)))

    def _can_send_alert(self, alert_type, device_id):
        """Check if we can send an alert (respecting cooldown)."""
        now = time.time()
        last_time = self.last_alerts.get(alert_type, {}).get(device_id, 0)
        return now - last_time >= self.alert_cooldown

    def _mark_alert_sent(self, alert_type, device_id):
        """Mark that an alert was sent."""
        if alert_type not in self.last_alerts:
            self.last_alerts[alert_type] = {}
        self.last_alerts[alert_type][device_id] = time.time()

    def check_outdoor_alerts(self):
        """
        Check Netatmo data for outdoor alert conditions.
        Alerts:
        - Rain started
        - Strong wind
        - Temperature change vs yesterday
        - Pressure change (headache alert)
        """
        if not self.netatmo_api:
            return

        # Get outdoor alert channel config
        outdoor_channel = self.config.get('slack', {}).get('channels', {}).get('outdoor_alert')
        if not outdoor_channel:
            logging.debug("Outdoor alert channel not configured, skipping alerts")
            return

        netatmo_devices = self.db.get_all_netatmo_devices()

        for device in netatmo_devices:
            device_id = device['device_id']
            device_name = device['device_name']
            module_type = device.get('module_type', '')

            try:
                # Get latest and previous data
                latest = self.db.get_latest_netatmo_data(device_id)
                if not latest:
                    continue

                previous = self.db.get_previous_netatmo_data(device_id)

                # === Rain Alert (NAModule3) ===
                if module_type == 'NAModule3':
                    self._check_rain_alert(device_id, device_name, latest, previous)

                # === Wind Alert (NAModule2) ===
                if module_type == 'NAModule2':
                    self._check_wind_alert(device_id, device_name, latest)

                # === Temperature Alert (outdoor modules) ===
                if module_type == 'NAModule1':
                    self._check_temperature_alert(device_id, device_name, latest)

                # === Pressure Alert (main station) ===
                if module_type == 'NAMain':
                    self._check_pressure_alert(device_id, device_name, latest)

            except Exception as e:
                logging.error("Error checking outdoor alerts for %s: %s", device_name, e)

    def _check_rain_alert(self, device_id, device_name, latest, previous):
        """Check if rain started."""
        if not self._can_send_alert('rain', device_id):
            return

        current_rain = latest.get('rain')
        previous_rain = previous.get('rain') if previous else None

        # Rain started: was 0 (or None), now > 0
        if current_rain is not None and current_rain > 0:
            if previous_rain is None or previous_rain == 0:
                message = "雨が降り始めました"
                details = "現在の雨量: {:.1f}mm | 24h累計: {}mm".format(
                    current_rain,
                    latest.get('rain_24h', '-')
                )
                self.slack.notify_outdoor_alert('rain', message, details, level='info')
                self._mark_alert_sent('rain', device_id)
                logging.info("[Alert] Rain started: %s", device_name)

    def _check_wind_alert(self, device_id, device_name, latest):
        """Check for strong wind conditions."""
        if not self._can_send_alert('wind', device_id):
            return

        wind_strength = latest.get('wind_strength')
        gust_strength = latest.get('gust_strength')

        if wind_strength is None:
            return

        # Wind thresholds (km/h) based on Japan Meteorological Agency
        # 10m/s = 36km/h: やや強い風 (傘がさせない)
        # 15m/s = 54km/h: 強い風 (風に向かって歩けない)
        # 20m/s = 72km/h: 非常に強い風 (立っていられない)

        message = None
        level = 'info'

        if wind_strength >= 72 or (gust_strength and gust_strength >= 72):
            message = "非常に強い風（暴風）です"
            level = 'danger'
        elif wind_strength >= 54 or (gust_strength and gust_strength >= 54):
            message = "強い風です。風に向かって歩きにくくなります"
            level = 'warning'
        elif wind_strength >= 36 or (gust_strength and gust_strength >= 36):
            message = "やや強い風です。傘がさしにくくなります"
            level = 'info'

        if message:
            details = "風速: {}km/h".format(wind_strength)
            if gust_strength:
                details += " | 突風: {}km/h".format(gust_strength)
            self.slack.notify_outdoor_alert('wind', message, details, level=level)
            self._mark_alert_sent('wind', device_id)
            logging.info("[Alert] Strong wind: %s - %dkm/h", device_name, wind_strength)

    def _check_temperature_alert(self, device_id, device_name, latest):
        """Check temperature change vs yesterday same time."""
        if not self._can_send_alert('temperature', device_id):
            return

        current_temp = latest.get('temperature')
        if current_temp is None:
            return

        # Get yesterday's data at same time
        yesterday = self.db.get_netatmo_data_yesterday_same_time(device_id)
        if not yesterday or yesterday.get('temperature') is None:
            return

        yesterday_temp = yesterday['temperature']
        temp_diff = current_temp - yesterday_temp

        # Alert if temperature changed by 2°C or more
        if abs(temp_diff) >= 2.0:
            if temp_diff > 0:
                message = "昨日より{:.1f}°C暑いです".format(temp_diff)
                alert_type = 'temperature_hot'
            else:
                message = "昨日より{:.1f}°C寒いです".format(abs(temp_diff))
                alert_type = 'temperature_cold'

            details = "現在: {:.1f}°C | 昨日同時刻: {:.1f}°C".format(current_temp, yesterday_temp)

            level = 'warning' if abs(temp_diff) >= 5.0 else 'info'
            self.slack.notify_outdoor_alert(alert_type, message, details, level=level)
            self._mark_alert_sent('temperature', device_id)
            logging.info("[Alert] Temperature change: %s - %.1f°C diff", device_name, temp_diff)

    def _check_pressure_alert(self, device_id, device_name, latest):
        """
        Check pressure changes for headache/weather sickness alerts.
        Based on research:
        - 4hPa change in 6 hours: mild warning
        - 6hPa change in 6 hours: moderate warning (headache likely)
        - 10hPa change in 6 hours: severe warning
        """
        if not self._can_send_alert('pressure', device_id):
            return

        current_pressure = latest.get('pressure')
        if current_pressure is None:
            return

        # Get pressure from 6 hours ago
        data_6h_ago = self.db.get_netatmo_data_hours_ago(device_id, 6)
        if not data_6h_ago or data_6h_ago.get('pressure') is None:
            return

        pressure_6h_ago = data_6h_ago['pressure']
        pressure_diff = current_pressure - pressure_6h_ago

        # Determine alert level
        message = None
        level = 'info'
        alert_type = 'pressure_down' if pressure_diff < 0 else 'pressure_up'

        abs_diff = abs(pressure_diff)

        if abs_diff >= 10:
            # Severe: rapid pressure change
            direction = "低下" if pressure_diff < 0 else "上昇"
            message = "気圧が急激に{}しています（気象病警戒）".format(direction)
            level = 'danger'
        elif abs_diff >= 6:
            # Moderate: headache likely
            direction = "下がって" if pressure_diff < 0 else "上がって"
            message = "気圧が{}います。頭痛に注意".format(direction)
            level = 'warning'
        elif abs_diff >= 4:
            # Mild: slight warning
            direction = "低下傾向" if pressure_diff < 0 else "上昇傾向"
            message = "気圧が{}です".format(direction)
            level = 'info'

        if message:
            details = "現在: {:.1f}hPa | 6時間前: {:.1f}hPa | 変化: {:+.1f}hPa".format(
                current_pressure, pressure_6h_ago, pressure_diff
            )

            # Add low pressure warning if below 1000hPa
            if current_pressure < 1000:
                details += " | 低気圧"

            self.slack.notify_outdoor_alert(alert_type, message, details, level=level)
            self._mark_alert_sent('pressure', device_id)
            logging.info("[Alert] Pressure change: %s - %.1fhPa diff", device_name, pressure_diff)

    def _is_sensor_device(self, device_type):
        """Check if device type is a sensor that records time series data."""
        sensor_types = [
            'Meter', 'MeterPlus', 'MeterPro', 'MeterPro(CO2)',
            'WoIOSensor', 'Hub 2', 'Outdoor Meter'
        ]
        return device_type in sensor_types

    def _is_outdoor_sensor(self, device_name):
        """Check if device is an outdoor sensor."""
        outdoor_keywords = ['防水温湿度計', '屋外', 'Outdoor']
        for keyword in outdoor_keywords:
            if keyword in device_name:
                return True
        return False

    def send_graph_report(self):
        """
        Send graph report for all sensor devices to #atmos-graph channel.
        Shows data from the last 24 hours.
        Separates outdoor and indoor sensors.
        Includes both SwitchBot and Netatmo sensors.
        """
        logging.info("Generating graph report for last 24 hours...")

        # Label for chart titles
        date_str = "直近24h"

        # Get all SwitchBot sensor devices
        sensor_devices = self.db.get_all_sensor_devices()

        # Separate outdoor and indoor sensor data
        outdoor_data = {}  # {device_name: sensor_data_list}
        indoor_data = {}   # {device_name: sensor_data_list}
        # Netatmo-specific data
        wind_data = {}     # {device_name: sensor_data_list} for wind sensors
        rain_data = {}     # {device_name: sensor_data_list} for rain sensors
        pressure_data = {} # {device_name: sensor_data_list} for pressure (indoor only)
        noise_data = {}    # {device_name: sensor_data_list} for noise (indoor only)
        devices_summary = []

        # Process SwitchBot sensors
        for device in sensor_devices:
            device_id = device['device_id']
            device_name = device['device_name']

            try:
                # Get last 24 hours data
                sensor_data = self.db.get_sensor_data_last_24h(device_id)

                if not sensor_data:
                    logging.debug("No data for %s in last 24 hours", device_name)
                    continue

                # Separate outdoor vs indoor
                if self._is_outdoor_sensor(device_name):
                    outdoor_data["[SB] " + device_name] = sensor_data
                else:
                    indoor_data["[SB] " + device_name] = sensor_data

                # Get latest values for summary
                latest = sensor_data[-1] if sensor_data else {}
                is_outdoor = self._is_outdoor_sensor(device_name)
                devices_summary.append({
                    'device_name': "[SB] " + device_name,
                    'source': 'SwitchBot',
                    'module_type': 'SwitchBot',
                    'temperature': {'latest': latest.get('temperature', '-')},
                    'humidity': {'latest': latest.get('humidity', '-')},
                    'co2': {'latest': latest.get('co2', '-')},
                    'pressure': {'latest': '-'},
                    'noise': {'latest': '-'},
                    'wind_strength': {'latest': '-'},
                    'rain_24h': {'latest': '-'},
                    'is_outdoor': is_outdoor
                })

            except Exception as e:
                logging.error("Error getting SwitchBot data for %s: %s", device_name, e)

        # Process Netatmo sensors
        if self.netatmo_api:
            netatmo_devices = self.db.get_all_netatmo_devices()

            for device in netatmo_devices:
                device_id = device['device_id']
                device_name = device['device_name']
                module_type = device.get('module_type', '')
                is_outdoor = device.get('is_outdoor', False)

                try:
                    # Get last 24 hours data
                    sensor_data = self.db.get_netatmo_data_last_24h(device_id)

                    if not sensor_data:
                        logging.debug("No Netatmo data for %s in last 24 hours", device_name)
                        continue

                    display_name = "[NA] " + device_name

                    # Categorize by module type
                    if module_type == 'NAModule2':
                        # Wind sensor
                        wind_data[display_name] = sensor_data
                    elif module_type == 'NAModule3':
                        # Rain sensor
                        rain_data[display_name] = sensor_data
                    elif is_outdoor:
                        # Outdoor temperature/humidity (NAModule1)
                        outdoor_data[display_name] = sensor_data
                    else:
                        # Indoor (NAMain, NAModule4)
                        indoor_data[display_name] = sensor_data
                        # Pressure and noise from main station
                        if module_type == 'NAMain':
                            pressure_data[display_name] = sensor_data
                            noise_data[display_name] = sensor_data

                    # Get latest values for summary
                    latest = sensor_data[-1] if sensor_data else {}
                    devices_summary.append({
                        'device_name': display_name,
                        'source': 'Netatmo',
                        'module_type': module_type,
                        'temperature': {'latest': latest.get('temperature', '-')},
                        'humidity': {'latest': latest.get('humidity', '-')},
                        'co2': {'latest': latest.get('co2', '-')},
                        'pressure': {'latest': latest.get('pressure', '-')},
                        'noise': {'latest': latest.get('noise', '-')},
                        'wind_strength': {'latest': latest.get('wind_strength', '-')},
                        'gust_strength': {'latest': latest.get('gust_strength', '-')},
                        'rain': {'latest': latest.get('rain', '-')},
                        'rain_24h': {'latest': latest.get('rain_24h', '-')},
                        'is_outdoor': is_outdoor
                    })

                except Exception as e:
                    logging.error("Error getting Netatmo data for %s: %s", device_name, e)

        if not outdoor_data and not indoor_data and not wind_data and not rain_data:
            logging.info("No sensor data collected for graph report")
            return

        # Generate charts
        # Get interval for downsampling from graph_report config (default: 10 minutes)
        interval_seconds = self.config.get('graph_report', {}).get('downsample_seconds', 600)

        # Use local chart generator if enabled (Raspberry Pi mode)
        if self.use_local_chart and self.local_chart_generator and self.slack_uploader:
            self._send_local_chart_report(
                outdoor_data, indoor_data, wind_data, rain_data,
                pressure_data, noise_data, date_str, interval_seconds
            )
            return

        # Default: Use QuickChart.io URL mode
        chart_urls = {}
        try:
            # Outdoor charts (temperature, humidity)
            if outdoor_data:
                chart_urls['outdoor_temp'] = self.chart_generator.generate_multi_device_chart(
                    outdoor_data, 'temperature', date_str, use_short_url=True,
                    interval_seconds=interval_seconds
                )
                chart_urls['outdoor_humidity'] = self.chart_generator.generate_multi_device_chart(
                    outdoor_data, 'humidity', date_str, use_short_url=True,
                    interval_seconds=interval_seconds
                )
                logging.debug("Generated outdoor charts")

            # Indoor charts (temperature, humidity, CO2)
            if indoor_data:
                chart_urls['indoor_temp'] = self.chart_generator.generate_multi_device_chart(
                    indoor_data, 'temperature', date_str, use_short_url=True,
                    interval_seconds=interval_seconds
                )
                chart_urls['indoor_humidity'] = self.chart_generator.generate_multi_device_chart(
                    indoor_data, 'humidity', date_str, use_short_url=True,
                    interval_seconds=interval_seconds
                )
                chart_urls['co2'] = self.chart_generator.generate_multi_device_chart(
                    indoor_data, 'co2', date_str, use_short_url=True,
                    interval_seconds=interval_seconds
                )
                logging.debug("Generated indoor charts")

            # Pressure chart (Netatmo main station only)
            if pressure_data:
                chart_urls['pressure'] = self.chart_generator.generate_multi_device_chart(
                    pressure_data, 'pressure', date_str, use_short_url=True,
                    interval_seconds=interval_seconds
                )
                logging.debug("Generated pressure chart")

            # Noise chart (Netatmo main station only)
            if noise_data:
                chart_urls['noise'] = self.chart_generator.generate_multi_device_chart(
                    noise_data, 'noise', date_str, use_short_url=True,
                    interval_seconds=interval_seconds
                )
                logging.debug("Generated noise chart")

            # Wind chart (Netatmo NAModule2) - combined wind speed and gust
            if wind_data:
                chart_urls['wind'] = self.chart_generator.generate_wind_chart(
                    wind_data, date_str, use_short_url=True,
                    interval_seconds=interval_seconds
                )
                # Wind direction chart
                chart_urls['wind_direction'] = self.chart_generator.generate_wind_direction_chart(
                    wind_data, date_str, use_short_url=True,
                    interval_seconds=interval_seconds
                )
                logging.debug("Generated wind charts")

            # Rain chart (Netatmo NAModule3) - combined bar (1h) and line (24h)
            if rain_data:
                chart_urls['rain'] = self.chart_generator.generate_rain_chart(
                    rain_data, date_str, use_short_url=True,
                    interval_seconds=interval_seconds
                )
                logging.debug("Generated rain chart")

        except Exception as e:
            logging.error("Error generating chart: %s", e)

        # Send to Slack #atmos-graph channel
        try:
            self.slack.notify_atmos_graph(date_str, devices_summary, chart_urls)
            logging.info("Sent graph report to #atmos-graph")
        except Exception as e:
            logging.error("Error sending graph report: %s", e)

    def _send_local_chart_report(self, outdoor_data, indoor_data, wind_data, rain_data,
                                  pressure_data, noise_data, date_str, interval_seconds,
                                  devices_summary=None):
        """
        Generate charts locally using matplotlib and upload to Slack.
        Used for Raspberry Pi deployment where QuickChart.io may be unreliable.

        Generates two sets of charts:
        - 12h charts with current downsample interval
        - 24h charts with 30-minute downsample interval
        """
        logging.info("Generating local charts with matplotlib...")

        # Time configurations
        # 12h: use configured interval (default 10 min)
        # 24h: use 30 min interval
        interval_12h = interval_seconds
        interval_24h = 1800  # 30 minutes

        chart_paths = {}
        try:
            # Generate 12h and 24h charts for each metric
            for hours, interval, suffix in [(12, interval_12h, '_12h'), (24, interval_24h, '_24h')]:
                # Outdoor charts
                if outdoor_data:
                    chart_paths['outdoor_temp' + suffix] = self.local_chart_generator.generate_multi_device_chart(
                        outdoor_data, 'temperature', date_str,
                        interval_seconds=interval, hours_range=hours
                    )
                    chart_paths['outdoor_humidity' + suffix] = self.local_chart_generator.generate_multi_device_chart(
                        outdoor_data, 'humidity', date_str,
                        interval_seconds=interval, hours_range=hours
                    )

                # Indoor charts
                if indoor_data:
                    chart_paths['indoor_temp' + suffix] = self.local_chart_generator.generate_multi_device_chart(
                        indoor_data, 'temperature', date_str,
                        interval_seconds=interval, hours_range=hours
                    )
                    chart_paths['indoor_humidity' + suffix] = self.local_chart_generator.generate_multi_device_chart(
                        indoor_data, 'humidity', date_str,
                        interval_seconds=interval, hours_range=hours
                    )
                    chart_paths['co2' + suffix] = self.local_chart_generator.generate_multi_device_chart(
                        indoor_data, 'co2', date_str,
                        interval_seconds=interval, hours_range=hours
                    )

                # Pressure chart
                if pressure_data:
                    chart_paths['pressure' + suffix] = self.local_chart_generator.generate_multi_device_chart(
                        pressure_data, 'pressure', date_str,
                        interval_seconds=interval, hours_range=hours
                    )

                # Noise chart
                if noise_data:
                    chart_paths['noise' + suffix] = self.local_chart_generator.generate_multi_device_chart(
                        noise_data, 'noise', date_str,
                        interval_seconds=interval, hours_range=hours
                    )

                # Wind charts
                if wind_data:
                    chart_paths['wind' + suffix] = self.local_chart_generator.generate_wind_chart(
                        wind_data, date_str,
                        interval_seconds=interval, hours_range=hours
                    )
                    chart_paths['wind_direction' + suffix] = self.local_chart_generator.generate_wind_direction_chart(
                        wind_data, date_str,
                        interval_seconds=interval, hours_range=hours
                    )

                # Rain chart
                if rain_data:
                    chart_paths['rain' + suffix] = self.local_chart_generator.generate_rain_chart(
                        rain_data, date_str,
                        interval_seconds=interval, hours_range=hours
                    )

                logging.debug("Generated local %dh charts", hours)

        except Exception as e:
            logging.error("Error generating local charts: %s", e)
            return

        # Post summary text first
        try:
            summary_text = self._build_sensor_summary(outdoor_data, indoor_data, wind_data, rain_data)
            if summary_text:
                self.slack_uploader.post_message(summary_text)
                logging.debug("Posted sensor summary to Slack")
        except Exception as e:
            logging.error("Error posting summary: %s", e)

        # Upload charts to Slack
        try:
            results = self.slack_uploader.upload_charts(chart_paths, date_str)
            success_count = sum(1 for v in results.values() if v)
            total_count = len(results)
            logging.info("Uploaded %d/%d charts to Slack", success_count, total_count)
        except Exception as e:
            logging.error("Error uploading charts to Slack: %s", e)
            # Cleanup any remaining files
            for path in chart_paths.values():
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

    def _build_sensor_summary(self, outdoor_data, indoor_data, wind_data, rain_data):
        """Build sensor summary text for Slack posting."""
        from datetime import datetime
        current_time = datetime.now().strftime('%H:%M')

        lines = ['*環境センサーレポート ({})* '.format(current_time)]

        # Outdoor section
        if outdoor_data:
            lines.append('*屋外*')
            for device_name, data in outdoor_data.items():
                if data:
                    latest = data[-1]
                    temp = latest.get('temperature')
                    humidity = latest.get('humidity')
                    co2 = latest.get('co2')
                    pressure = latest.get('pressure')
                    noise = latest.get('noise')
                    wind = latest.get('wind_strength')
                    gust = latest.get('gust_strength')

                    parts = []
                    if temp is not None:
                        parts.append('{}°C'.format(temp))
                    if humidity is not None:
                        parts.append('{}%'.format(humidity))
                    if co2 is not None:
                        parts.append('{}ppm'.format(co2))
                    if pressure is not None:
                        parts.append('{}hPa'.format(pressure))
                    if noise is not None:
                        parts.append('{}dB'.format(noise))

                    line = '{}: {}'.format(device_name, ' / '.join(parts) if parts else '-')
                    lines.append(line)

        # Wind data (separate because it's a different structure)
        if wind_data:
            for device_name, data in wind_data.items():
                if data:
                    latest = data[-1]
                    wind_kmh = latest.get('wind_strength')
                    gust_kmh = latest.get('gust_strength')
                    wind_ms = round(wind_kmh / 3.6, 1) if wind_kmh else None
                    gust_ms = round(gust_kmh / 3.6, 1) if gust_kmh else None

                    if wind_ms is not None:
                        line = '{}: {}m/s'.format(device_name, wind_ms)
                        if gust_ms is not None:
                            line += ' (突風:{}m/s)'.format(gust_ms)
                        lines.append(line)

        # Indoor section
        if indoor_data:
            lines.append('')
            lines.append('*屋内*')
            for device_name, data in indoor_data.items():
                if data:
                    latest = data[-1]
                    temp = latest.get('temperature')
                    humidity = latest.get('humidity')
                    co2 = latest.get('co2')
                    pressure = latest.get('pressure')
                    noise = latest.get('noise')

                    parts = []
                    if temp is not None:
                        parts.append('{}°C'.format(temp))
                    if humidity is not None:
                        parts.append('{}%'.format(humidity))
                    if co2 is not None:
                        parts.append('{}ppm'.format(co2))
                    if pressure is not None:
                        parts.append('{}hPa'.format(pressure))
                    if noise is not None:
                        parts.append('{}dB'.format(noise))

                    line = '{}: {}'.format(device_name, ' / '.join(parts) if parts else '-')
                    lines.append(line)

        return '\n'.join(lines) if len(lines) > 1 else None

    def check_graph_report(self):
        """Check if it's time to send graph report (every N minutes)."""
        report_config = self.config.get('graph_report', {})
        if not report_config.get('enabled', False):
            return

        interval_minutes = report_config.get('interval_minutes', 5)
        interval_seconds = interval_minutes * 60

        now = time.time()
        if now - self.last_graph_report >= interval_seconds:
            self.send_graph_report()
            self.last_graph_report = now

    def run(self):
        """Main monitoring loop."""
        global running

        # Build device map
        logging.info("Fetching device list...")
        self.device_map = build_device_map(self.api, self.config)

        # Count devices by category
        counts = {'ignore': 0, 'polling': 0, 'webhook': 0}
        for info in self.device_map.values():
            counts[info['category']] += 1

        logging.info(
            "Devices: %d total (%d polling, %d webhook, %d ignored)",
            len(self.device_map), counts['polling'], counts['webhook'], counts['ignore']
        )

        # Setup webhook server
        webhook_enabled = self.setup_webhook_server()

        # Register webhook if enabled and URL available
        # Always register for Quick Tunnel (trycloudflare.com) since URL changes on restart
        if webhook_enabled and self.webhook_url and 'localhost' not in self.webhook_url:
            if 'trycloudflare.com' in self.webhook_url:
                logging.info("Quick Tunnel detected - cleaning up old webhooks and registering new URL")
            self.register_webhook()

        # Send startup notification
        if self.config.get('slack', {}).get('notify_startup', True):
            self.slack.notify_startup(counts['polling'] + counts['webhook'])

        # Get polling interval
        interval = self.config.get('monitor', {}).get('interval_seconds', 1800)
        logging.info("SwitchBot polling interval: %d seconds", interval)

        # Get Netatmo polling interval (default: 10 minutes)
        netatmo_interval = self.config.get('netatmo', {}).get('interval_seconds', 600)
        if self.netatmo_api:
            logging.info("Netatmo polling interval: %d seconds", netatmo_interval)

        # Get Google Nest polling interval (default: 5 minutes)
        nest_interval = self.config.get('google_nest', {}).get('interval_seconds', 300)
        if self.nest_api:
            logging.info("Google Nest polling interval: %d seconds", nest_interval)

        # Get graph report interval
        graph_interval = self.config.get('graph_report', {}).get('interval_minutes', 5)
        logging.info("Graph report interval: %d minutes", graph_interval)

        # Initial poll
        self.poll_devices()

        # Initial Netatmo poll
        if self.netatmo_api:
            self.poll_netatmo()
            self.last_netatmo_poll = time.time()

        # Initial Google Nest poll
        if self.nest_api:
            self.poll_nest()
            self.last_nest_poll = time.time()

        # Send initial graph report immediately after first poll
        if self.config.get('graph_report', {}).get('enabled', False):
            logging.info("Sending initial graph report...")
            self.send_graph_report()

        # Initialize graph report timer
        self.last_graph_report = time.time()

        # Main loop
        last_poll = time.time()
        while running:
            now = time.time()

            # Check if it's time to poll SwitchBot
            if now - last_poll >= interval:
                self.poll_devices()
                last_poll = now

            # Check if it's time to poll Netatmo
            if self.netatmo_api and now - self.last_netatmo_poll >= netatmo_interval:
                self.poll_netatmo()
                self.last_netatmo_poll = now

            # Check if it's time to poll Google Nest
            if self.nest_api and now - self.last_nest_poll >= nest_interval:
                self.poll_nest()
                self.last_nest_poll = now

            # Check for graph report (every 5 minutes)
            self.check_graph_report()

            # Sleep briefly
            time.sleep(1)

        # Cleanup
        self.shutdown()

    def shutdown(self):
        """Clean shutdown."""
        logging.info("Shutting down...")

        # Stop webhook server
        if self.webhook_server:
            self.webhook_server.stop()

        # Stop tunnel
        if self.tunnel:
            self.tunnel.stop()

        # Cleanup old history
        history_days = self.config.get('database', {}).get('history_days', 30)
        if history_days > 0:
            deleted = self.db.cleanup_old_history(history_days)
            if deleted > 0:
                logging.info("Cleaned up %d old history records", deleted)

        # Cleanup old sensor data (SwitchBot)
        sensor_days = self.config.get('database', {}).get('sensor_data_days', 7)
        if sensor_days > 0:
            deleted = self.db.cleanup_old_sensor_data(sensor_days)
            if deleted > 0:
                logging.info("Cleaned up %d old SwitchBot sensor data records", deleted)

        # Cleanup old Netatmo data
        netatmo_days = self.config.get('database', {}).get('netatmo_data_days', 7)
        if netatmo_days > 0:
            deleted = self.db.cleanup_old_netatmo_data(netatmo_days)
            if deleted > 0:
                logging.info("Cleaned up %d old Netatmo data records", deleted)

        logging.info("Shutdown complete")


def main():
    """Entry point."""
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Check for config path argument
    config_path = 'config.json'
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    # Make config path absolute
    if not os.path.isabs(config_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, config_path)

    # Load configuration
    config = load_config(config_path)

    # Setup logging
    log_config = config.get('logging', {})
    setup_logging(
        log_level=log_config.get('level', 'INFO'),
        log_file=log_config.get('file')
    )

    logging.info("Starting SwitchBot Monitor...")

    # Run monitor
    monitor = SwitchBotMonitor(config)
    monitor.run()


if __name__ == '__main__':
    main()
