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
from database import DeviceDatabase
from slack_notifier import SlackNotifier
from webhook_server import WebhookServer, parse_webhook_event
from cloudflare_tunnel import CloudflareTunnel
from chart_generator import ChartGenerator


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

        # Graph report tracking (5-minute interval)
        self.last_graph_report = 0

        # Netatmo polling tracking (separate interval)
        self.last_netatmo_poll = 0

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

                    logging.info(
                        "[Netatmo] %s (%s/%s): %s",
                        device_name, station_name, location, ", ".join(parts)
                    )

            logging.info("Netatmo polling complete: %d readings", len(readings))

        except Exception as e:
            logging.error("Error polling Netatmo: %s", e)
            if self.config.get('slack', {}).get('notify_errors', False):
                self.slack.notify_error("Netatmo: {}".format(str(e)))

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
        Shows data from today midnight to now.
        Separates outdoor and indoor sensors.
        Includes both SwitchBot and Netatmo sensors.
        """
        date_str = datetime.now().strftime('%Y-%m-%d')
        logging.info("Generating graph report for %s...", date_str)

        # Get all SwitchBot sensor devices
        sensor_devices = self.db.get_all_sensor_devices()

        # Separate outdoor and indoor sensor data
        outdoor_data = {}  # {device_name: sensor_data_list}
        indoor_data = {}   # {device_name: sensor_data_list}
        devices_summary = []

        # Process SwitchBot sensors
        for device in sensor_devices:
            device_id = device['device_id']
            device_name = device['device_name']

            try:
                # Get today's data
                sensor_data = self.db.get_sensor_data_for_date(device_id, date_str)

                if not sensor_data:
                    logging.debug("No data for %s on %s", device_name, date_str)
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
                    'temperature': {'latest': latest.get('temperature', '-')},
                    'humidity': {'latest': latest.get('humidity', '-')},
                    'co2': {'latest': latest.get('co2', '-')},
                    'pressure': {'latest': '-'},
                    'noise': {'latest': '-'},
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
                is_outdoor = device.get('is_outdoor', False)

                try:
                    # Get today's data
                    sensor_data = self.db.get_netatmo_data_for_date(device_id, date_str)

                    if not sensor_data:
                        logging.debug("No Netatmo data for %s on %s", device_name, date_str)
                        continue

                    # Separate outdoor vs indoor
                    display_name = "[NA] " + device_name
                    if is_outdoor:
                        outdoor_data[display_name] = sensor_data
                    else:
                        indoor_data[display_name] = sensor_data

                    # Get latest values for summary
                    latest = sensor_data[-1] if sensor_data else {}
                    devices_summary.append({
                        'device_name': display_name,
                        'source': 'Netatmo',
                        'temperature': {'latest': latest.get('temperature', '-')},
                        'humidity': {'latest': latest.get('humidity', '-')},
                        'co2': {'latest': latest.get('co2', '-')},
                        'pressure': {'latest': latest.get('pressure', '-')},
                        'noise': {'latest': latest.get('noise', '-')},
                        'is_outdoor': is_outdoor
                    })

                except Exception as e:
                    logging.error("Error getting Netatmo data for %s: %s", device_name, e)

        if not outdoor_data and not indoor_data:
            logging.info("No sensor data collected for graph report")
            return

        # Generate charts (5 total: outdoor temp/humidity, indoor temp/humidity, CO2)
        # Get interval for downsampling from config
        interval_seconds = self.config.get('monitor', {}).get('interval_seconds', 1800)
        chart_urls = {}
        try:
            # Outdoor charts
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

            # Indoor charts
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

        except Exception as e:
            logging.error("Error generating chart: %s", e)

        # Send to Slack #atmos-graph channel
        try:
            self.slack.notify_atmos_graph(date_str, devices_summary, chart_urls)
            logging.info("Sent graph report to #atmos-graph")
        except Exception as e:
            logging.error("Error sending graph report: %s", e)

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

        # Get graph report interval
        graph_interval = self.config.get('graph_report', {}).get('interval_minutes', 5)
        logging.info("Graph report interval: %d minutes", graph_interval)

        # Initial poll
        self.poll_devices()

        # Initial Netatmo poll
        if self.netatmo_api:
            self.poll_netatmo()
            self.last_netatmo_poll = time.time()

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
