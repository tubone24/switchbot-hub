#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SwitchBot Device Monitor
Monitors SwitchBot devices and sends Slack notifications on state changes.

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


# Global flag for graceful shutdown
running = True


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global running
    logging.info("Received signal %s, shutting down...", signum)
    running = False


def setup_logging(log_level='INFO', log_file=None):
    """
    Setup logging configuration.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional log file path
    """
    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers
    )


def load_config(config_path):
    """
    Load configuration from JSON file.

    Args:
        config_path: Path to config.json

    Returns:
        dict: Configuration dictionary
    """
    if not os.path.exists(config_path):
        logging.error("Config file not found: %s", config_path)
        logging.error("Please copy config.json.example to config.json and configure it")
        sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def monitor_devices(api, db, slack, config):
    """
    Single monitoring cycle - fetch all device states and check for changes.

    Args:
        api: SwitchBotAPI instance
        db: DeviceDatabase instance
        slack: SlackNotifier instance
        config: Configuration dict
    """
    try:
        # Get list of devices to monitor (if specified) or all
        device_filter = config.get('monitor', {}).get('device_ids', [])

        # Fetch all devices
        devices_data = api.get_devices()
        device_list = devices_data.get('deviceList', [])

        logging.debug("Found %d devices", len(device_list))

        for device in device_list:
            device_id = device.get('deviceId')
            device_name = device.get('deviceName', 'Unknown')
            device_type = device.get('deviceType', 'Unknown')

            # Skip if device filter is set and this device isn't in it
            if device_filter and device_id not in device_filter:
                logging.debug("Skipping device %s (not in filter)", device_name)
                continue

            try:
                # Get device status
                status = api.get_device_status(device_id)

                # Get previous state
                previous = db.get_device_state(device_id)
                previous_status = previous['status'] if previous else None

                # Save new state and check if changed
                changed = db.save_device_state(
                    device_id, device_name, device_type, status
                )

                if changed:
                    # Detect what changed
                    changes = db.get_changes(device_id, previous_status, status)

                    logging.info(
                        "Device %s (%s) state changed: %s",
                        device_name, device_type, changes
                    )

                    # Send Slack notification
                    slack.notify_device_change(
                        device_name, device_type, changes, status
                    )
                else:
                    logging.debug("Device %s unchanged", device_name)

            except Exception as e:
                logging.error(
                    "Error fetching status for %s: %s",
                    device_name, str(e)
                )
                # Optionally notify about errors
                if config.get('slack', {}).get('notify_errors', False):
                    slack.notify_error(str(e), device_name)

    except Exception as e:
        logging.error("Error in monitoring cycle: %s", str(e))
        if config.get('slack', {}).get('notify_errors', False):
            slack.notify_error(str(e))


def run_monitor(config_path='config.json'):
    """
    Main monitoring loop.

    Args:
        config_path: Path to configuration file
    """
    global running

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Load configuration
    config = load_config(config_path)

    # Setup logging
    log_config = config.get('logging', {})
    setup_logging(
        log_level=log_config.get('level', 'INFO'),
        log_file=log_config.get('file')
    )

    logging.info("Starting SwitchBot Monitor...")

    # Initialize components
    switchbot_config = config['switchbot']
    api = SwitchBotAPI(
        token=switchbot_config['token'],
        secret=switchbot_config['secret']
    )

    db_path = config.get('database', {}).get('path', 'device_states.db')
    db = DeviceDatabase(db_path)

    slack_config = config.get('slack', {})
    slack = SlackNotifier(
        webhook_url=slack_config.get('webhook_url', ''),
        enabled=slack_config.get('enabled', True)
    )

    # Get monitoring interval (default 5 minutes)
    interval = config.get('monitor', {}).get('interval_seconds', 300)

    # Initial device count for startup notification
    try:
        devices_data = api.get_devices()
        device_count = len(devices_data.get('deviceList', []))
        logging.info("Found %d SwitchBot devices", device_count)

        if slack_config.get('notify_startup', True):
            slack.notify_startup(device_count)
    except Exception as e:
        logging.error("Failed to fetch initial device list: %s", str(e))
        device_count = 0

    logging.info("Monitoring every %d seconds", interval)

    # Main loop
    while running:
        monitor_devices(api, db, slack, config)

        # Sleep in small increments to allow graceful shutdown
        sleep_time = 0
        while running and sleep_time < interval:
            time.sleep(1)
            sleep_time += 1

    # Cleanup
    logging.info("Monitor stopped")

    # Optional: cleanup old history
    history_days = config.get('database', {}).get('history_days', 30)
    if history_days > 0:
        deleted = db.cleanup_old_history(history_days)
        if deleted > 0:
            logging.info("Cleaned up %d old history records", deleted)


def main():
    """Entry point."""
    # Check for config path argument
    config_path = 'config.json'
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    # Make config path absolute if relative
    if not os.path.isabs(config_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, config_path)

    run_monitor(config_path)


if __name__ == '__main__':
    main()
