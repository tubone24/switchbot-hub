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

        # CO2 sensor
        if 'CO2' in status:
            co2 = status.get('CO2')
            summaries.append("CO2: {}ppm".format(co2))

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

    def notify_daily_report(self, device_name, date_str, summary, chart_urls=None):
        """
        Send daily sensor report with charts.

        Args:
            device_name: Device name
            date_str: Date string (YYYY-MM-DD)
            summary: Daily summary dict from database
            chart_urls: Dict of chart URLs {name: url}

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Build summary text
        summary_lines = []
        if summary:
            if summary.get('temperature', {}).get('avg') is not None:
                t = summary['temperature']
                summary_lines.append("Temperature: {}C (min: {}C, max: {}C)".format(
                    t['avg'], t['min'], t['max']
                ))

            if summary.get('humidity', {}).get('avg') is not None:
                h = summary['humidity']
                summary_lines.append("Humidity: {}% (min: {}%, max: {}%)".format(
                    h['avg'], h['min'], h['max']
                ))

            if summary.get('co2', {}).get('avg') is not None:
                c = summary['co2']
                summary_lines.append("CO2: {}ppm (min: {}ppm, max: {}ppm)".format(
                    c['avg'], c['min'], c['max']
                ))

        summary_text = '\n'.join(summary_lines) if summary_lines else "No data"

        # Plain text fallback
        text = "[SwitchBot] Daily Report - {} ({})\n{}".format(
            device_name, date_str, summary_text
        )

        # Rich Block Kit format
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Daily Sensor Report",
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
                        "text": "*Date:*\n{}".format(date_str)
                    }
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Summary:*\n```{}```".format(summary_text)
                }
            }
        ]

        # Add chart images
        if chart_urls:
            for chart_name, url in chart_urls.items():
                if url:
                    # Use image block for charts
                    chart_title = {
                        'temp_humidity': 'Temperature & Humidity',
                        'co2': 'CO2 Level'
                    }.get(chart_name, chart_name)

                    blocks.append({
                        "type": "image",
                        "title": {
                            "type": "plain_text",
                            "text": chart_title
                        },
                        "image_url": url,
                        "alt_text": chart_title
                    })

        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Generated at: {}".format(timestamp)
                }
            ]
        })

        return self.send_message(text, blocks)

    def notify_multi_device_report(self, date_str, devices_summary, chart_url=None):
        """
        Send report comparing multiple devices.

        Args:
            date_str: Date string
            devices_summary: Dict of {device_name: summary}
            chart_url: Comparison chart URL

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Build comparison table
        table_lines = []
        for device_name, summary in devices_summary.items():
            if summary:
                temp = summary.get('temperature', {}).get('avg', '-')
                humidity = summary.get('humidity', {}).get('avg', '-')
                co2 = summary.get('co2', {}).get('avg', '-')
                table_lines.append("{}: {}C / {}% / {}ppm".format(
                    device_name, temp, humidity, co2
                ))

        table_text = '\n'.join(table_lines) if table_lines else "No data"

        text = "[SwitchBot] Multi-Device Report ({})\n{}".format(date_str, table_text)

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Multi-Device Sensor Report",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Date:* {}\n*Devices (Temp / Humidity / CO2):*\n```{}```".format(
                        date_str, table_text
                    )
                }
            }
        ]

        if chart_url:
            blocks.append({
                "type": "image",
                "title": {
                    "type": "plain_text",
                    "text": "Comparison Chart"
                },
                "image_url": chart_url,
                "alt_text": "Multi-device comparison chart"
            })

        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Generated at: {}".format(timestamp)
                }
            ]
        })

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
