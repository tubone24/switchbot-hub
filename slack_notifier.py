# -*- coding: utf-8 -*-
"""
Slack notification module using Incoming Webhooks.
Python 3.7+ compatible, requires only requests library.
"""
import json
import requests
from datetime import datetime


class SlackNotifier:
    """Send notifications to Slack via Incoming Webhooks."""

    def __init__(self, webhook_url, enabled=True):
        """
        Initialize Slack notifier.

        Args:
            webhook_url: Slack Incoming Webhook URL
            enabled: Whether notifications are enabled
        """
        self.webhook_url = webhook_url
        self.enabled = enabled

    def send_message(self, text, blocks=None):
        """
        Send a message to Slack.

        Args:
            text: Plain text message (fallback for notifications)
            blocks: Optional Block Kit blocks for rich formatting

        Returns:
            bool: True if sent successfully
        """
        if not self.enabled:
            return True

        if not self.webhook_url:
            print("[Slack] Webhook URL not configured, skipping notification")
            return False

        payload = {'text': text}
        if blocks:
            payload['blocks'] = blocks

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print("[Slack] Failed to send notification: {}".format(e))
            return False

    def notify_device_change(self, device_name, device_type, changes, status):
        """
        Send notification about device state change.

        Args:
            device_name: Name of the device
            device_type: Type of the device
            changes: List of change dicts
            status: Current device status

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Build change text
        change_lines = []
        for change in changes:
            change_lines.append("  - {}".format(change['message']))

        change_text = '\n'.join(change_lines) if change_lines else "  (Initial state recorded)"

        # Plain text fallback
        text = "[SwitchBot] {} ({}) state changed:\n{}".format(
            device_name, device_type, change_text
        )

        # Rich Block Kit format
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "SwitchBot Device Update",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": "*Device:*\n{}".format(device_name)
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*Type:*\n{}".format(device_type)
                    }
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Changes:*\n```{}```".format(change_text)
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Updated at: {}".format(timestamp)
                    }
                ]
            },
            {
                "type": "divider"
            }
        ]

        # Add current status summary for common device types
        status_text = self._format_status_summary(device_type, status)
        if status_text:
            blocks.insert(-1, {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Current Status:*\n{}".format(status_text)
                }
            })

        return self.send_message(text, blocks)

    def _format_status_summary(self, device_type, status):
        """
        Format status summary based on device type.

        Args:
            device_type: Type of device
            status: Status dict

        Returns:
            str: Formatted status text
        """
        if not status:
            return None

        summaries = []

        # Temperature/Humidity sensors (Meter, MeterPlus, WoIOSensor, Hub2)
        if 'temperature' in status:
            temp = status.get('temperature')
            summaries.append("Temperature: {}C".format(temp))

        if 'humidity' in status:
            humidity = status.get('humidity')
            summaries.append("Humidity: {}%".format(humidity))

        # Battery level
        if 'battery' in status:
            battery = status.get('battery')
            summaries.append("Battery: {}%".format(battery))

        # Bot (switch)
        if 'power' in status:
            power = status.get('power')
            summaries.append("Power: {}".format(power))

        # Curtain
        if 'slidePosition' in status:
            pos = status.get('slidePosition')
            summaries.append("Position: {}%".format(pos))

        # Plug
        if 'voltage' in status:
            voltage = status.get('voltage')
            summaries.append("Voltage: {}V".format(voltage))

        if 'weight' in status:
            weight = status.get('weight')
            summaries.append("Power: {}W".format(weight))

        # Motion/Contact sensors
        if 'moveDetected' in status:
            detected = "Yes" if status.get('moveDetected') else "No"
            summaries.append("Motion: {}".format(detected))

        if 'openState' in status:
            state = status.get('openState')
            summaries.append("Door: {}".format(state))

        # Lock
        if 'lockState' in status:
            lock_state = status.get('lockState')
            summaries.append("Lock: {}".format(lock_state))

        if 'doorState' in status:
            door_state = status.get('doorState')
            summaries.append("Door: {}".format(door_state))

        if summaries:
            return '\n'.join(['- {}'.format(s) for s in summaries])
        return None

    def notify_error(self, error_message, device_name=None):
        """
        Send error notification.

        Args:
            error_message: Error description
            device_name: Optional device name if error is device-specific

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if device_name:
            text = "[SwitchBot Error] {}: {}".format(device_name, error_message)
        else:
            text = "[SwitchBot Error] {}".format(error_message)

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "SwitchBot Monitor Error",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Error:*\n```{}```".format(error_message)
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Time: {}".format(timestamp)
                    }
                ]
            }
        ]

        if device_name:
            blocks.insert(1, {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Device:* {}".format(device_name)
                }
            })

        return self.send_message(text, blocks)

    def notify_startup(self, device_count):
        """
        Send startup notification.

        Args:
            device_count: Number of devices being monitored

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        text = "[SwitchBot Monitor] Started monitoring {} devices".format(device_count)

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "SwitchBot Monitor Started",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Now monitoring *{}* devices".format(device_count)
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Started at: {}".format(timestamp)
                    }
                ]
            }
        ]

        return self.send_message(text, blocks)


if __name__ == '__main__':
    # Simple test (won't actually send without valid webhook)
    notifier = SlackNotifier("https://hooks.slack.com/services/xxx", enabled=False)

    # Test change notification formatting
    changes = [
        {'field': 'temperature', 'old_value': 25.0, 'new_value': 26.0, 'message': 'temperature: 25.0 -> 26.0'},
        {'field': 'humidity', 'old_value': 60, 'new_value': 58, 'message': 'humidity: 60 -> 58'}
    ]
    status = {'temperature': 26.0, 'humidity': 58, 'battery': 90}

    print("Test notification format would be sent for device change")
    print("Changes: {}".format(changes))
    print("Status: {}".format(status))
    print("Test completed!")
