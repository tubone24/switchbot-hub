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

        # Initialize API
        switchbot_config = config['switchbot']
        self.api = SwitchBotAPI(
            token=switchbot_config['token'],
            secret=switchbot_config['secret']
        )

        # Initialize database
        db_path = config.get('database', {}).get('path', 'device_states.db')
        self.db = DeviceDatabase(db_path)

        # Initialize Slack
        slack_config = config.get('slack', {})
        self.slack = SlackNotifier(
            webhook_url=slack_config.get('webhook_url', ''),
            enabled=slack_config.get('enabled', True)
        )

        # Device map
        self.device_map = {}

        # Webhook server
        self.webhook_server = None
        self.tunnel = None
        self.webhook_url = None

        # Chart generator
        self.chart_generator = ChartGenerator()

        # Daily report tracking
        self.last_report_date = None

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

    def register_webhook(self):
        """Register webhook URL with SwitchBot API."""
        if not self.webhook_url:
            logging.warning("No webhook URL available")
            return False

        # Check if webhook already registered
        try:
            current = self.api.query_webhook()
            urls = current.get('urls', [])
            logging.info("Current webhooks: %s", urls)

            if self.webhook_url in urls:
                logging.info("Webhook already registered")
                return True
        except Exception as e:
            logging.warning("Failed to query webhook: %s", e)

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

            device_name = device_info['device_name']
            device_type = device_info['device_type']
            status = parsed['status']

            logging.info(
                "[Webhook] Device: %s (%s), Status: %s",
                device_name, device_type, status
            )

            # Get previous state
            previous = self.db.get_device_state(device_info['device_id'])
            previous_status = previous['status'] if previous else None

            # Save new state
            changed = self.db.save_device_state(
                device_info['device_id'],
                device_name,
                device_type,
                status
            )

            if changed:
                changes = self.db.get_changes(device_info['device_id'], previous_status, status)
                logging.info("State changed: %s", changes)

                # Send Slack notification
                self.slack.notify_device_change(device_name, device_type, changes, status)

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

                if changed:
                    changes = self.db.get_changes(device_id, previous_status, status)
                    logging.info(
                        "[Polling] Device %s (%s) state changed: %s",
                        device_name, device_type, changes
                    )
                    self.slack.notify_device_change(device_name, device_type, changes, status)
                else:
                    logging.debug("Device %s unchanged", device_name)

            except Exception as e:
                logging.error("Error polling %s: %s", device_name, e)
                if self.config.get('slack', {}).get('notify_errors', False):
                    self.slack.notify_error(str(e), device_name)

    def _is_sensor_device(self, device_type):
        """Check if device type is a sensor that records time series data."""
        sensor_types = [
            'Meter', 'MeterPlus', 'MeterPro', 'MeterPro(CO2)',
            'WoIOSensor', 'Hub 2', 'Outdoor Meter'
        ]
        return device_type in sensor_types

    def send_daily_report(self, date_str=None):
        """
        Send daily report for all sensor devices.

        Args:
            date_str: Date to report (YYYY-MM-DD), defaults to yesterday
        """
        if date_str is None:
            # Default to yesterday
            from datetime import timedelta
            yesterday = datetime.utcnow() - timedelta(days=1)
            date_str = yesterday.strftime('%Y-%m-%d')

        logging.info("Generating daily report for %s...", date_str)

        # Get all sensor devices
        sensor_devices = self.db.get_all_sensor_devices()

        if not sensor_devices:
            logging.info("No sensor data available for report")
            return

        for device in sensor_devices:
            device_id = device['device_id']
            device_name = device['device_name']

            try:
                # Get daily data and summary
                sensor_data = self.db.get_sensor_data_for_date(device_id, date_str)
                summary = self.db.get_daily_summary(device_id, date_str)

                if not sensor_data:
                    logging.debug("No data for %s on %s", device_name, date_str)
                    continue

                # Generate charts
                chart_urls = self.chart_generator.generate_sensor_chart(
                    sensor_data, device_name, date_str, use_short_url=True
                )

                # Send report to Slack
                self.slack.notify_daily_report(
                    device_name, date_str, summary, chart_urls
                )

                logging.info("Sent daily report for %s", device_name)

            except Exception as e:
                logging.error("Error generating report for %s: %s", device_name, e)

    def check_daily_report(self):
        """Check if it's time to send daily report (at configured hour)."""
        report_config = self.config.get('daily_report', {})
        if not report_config.get('enabled', False):
            return

        report_hour = report_config.get('hour', 8)  # Default 8 AM
        now = datetime.now()

        # Check if it's the right hour and we haven't sent today
        today = now.strftime('%Y-%m-%d')
        if now.hour == report_hour and self.last_report_date != today:
            # Send report for yesterday
            self.send_daily_report()
            self.last_report_date = today

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
        if webhook_enabled and self.webhook_url and 'localhost' not in self.webhook_url:
            self.register_webhook()

        # Send startup notification
        if self.config.get('slack', {}).get('notify_startup', True):
            self.slack.notify_startup(counts['polling'] + counts['webhook'])

        # Get polling interval
        interval = self.config.get('monitor', {}).get('interval_seconds', 1800)
        logging.info("Polling interval: %d seconds", interval)

        # Initial poll
        self.poll_devices()

        # Main loop
        last_poll = time.time()
        while running:
            # Check if it's time to poll
            now = time.time()
            if now - last_poll >= interval:
                self.poll_devices()
                last_poll = now

            # Check for daily report
            self.check_daily_report()

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

        # Cleanup old sensor data
        sensor_days = self.config.get('database', {}).get('sensor_data_days', 7)
        if sensor_days > 0:
            deleted = self.db.cleanup_old_sensor_data(sensor_days)
            if deleted > 0:
                logging.info("Cleaned up %d old sensor data records", deleted)

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
