# -*- coding: utf-8 -*-
"""
Slack notification module using Incoming Webhooks.
Python 3.7+ compatible, requires only requests library.
Supports multiple channels for different notification types.
"""
import json
import requests
from datetime import datetime


class SlackNotifier:
    """Send notifications to Slack via Incoming Webhooks."""

    # Security device types
    SECURITY_DEVICE_TYPES = [
        'Smart Lock', 'Smart Lock Pro', 'Lock',
        'Contact Sensor', 'Motion Sensor',
        'Keypad', 'Keypad Touch',
        'Video Doorbell'
    ]

    # Atmosphere sensor device types
    ATMOS_DEVICE_TYPES = [
        'Meter', 'MeterPlus', 'MeterPro', 'MeterPro(CO2)',
        'WoIOSensor', 'Hub 2', 'Outdoor Meter'
    ]

    def __init__(self, config):
        """
        Initialize Slack notifier with channel configuration.

        Args:
            config: Slack config dict with 'channels' and other settings
        """
        self.enabled = config.get('enabled', True)
        self.channels = config.get('channels', {})

        # Backwards compatibility: if 'webhook_url' is provided, use for all
        if 'webhook_url' in config and not self.channels:
            self.channels = {
                'home_security': config['webhook_url'],
                'atmos_update': config['webhook_url'],
                'atmos_graph': config['webhook_url']
            }

    def _send_to_channel(self, channel, text, blocks=None):
        """
        Send a message to a specific Slack channel.

        Args:
            channel: Channel key ('home_security', 'atmos_update', 'atmos_graph')
            text: Plain text message (fallback for notifications)
            blocks: Optional Block Kit blocks for rich formatting

        Returns:
            bool: True if sent successfully
        """
        if not self.enabled:
            return True

        webhook_url = self.channels.get(channel)
        if not webhook_url:
            print("[Slack] No webhook URL configured for channel: {}".format(channel))
            return False

        payload = {'text': text}
        if blocks:
            payload['blocks'] = blocks

        try:
            response = requests.post(
                webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print("[Slack] Failed to send to {}: {}".format(channel, e))
            return False

    def get_device_category(self, device_type):
        """
        Determine device category based on type.

        Args:
            device_type: SwitchBot device type string

        Returns:
            str: 'security', 'atmos', or 'other'
        """
        if device_type in self.SECURITY_DEVICE_TYPES:
            return 'security'
        elif device_type in self.ATMOS_DEVICE_TYPES:
            return 'atmos'
        return 'other'

    def _get_security_message_ja(self, device_name, device_type, status):
        """
        Generate Japanese security notification message.

        Args:
            device_name: Device name
            device_type: Device type
            status: Current status dict

        Returns:
            str: Japanese message
        """
        # Lock devices
        if device_type in ['Smart Lock', 'Smart Lock Pro', 'Lock']:
            lock_state = status.get('lockState', '')
            if lock_state == 'locked':
                return "{}が施錠されました".format(device_name)
            elif lock_state == 'unlocked':
                return "{}が解錠されました".format(device_name)
            elif lock_state == 'jammed':
                return "{}がジャム（詰まり）状態です！".format(device_name)
            else:
                return "{}の状態が変わりました: {}".format(device_name, lock_state)

        # Contact Sensor (door/window open/close)
        if device_type == 'Contact Sensor':
            open_state = status.get('openState', '')
            if open_state == 'open':
                return "{}が開きました".format(device_name)
            elif open_state == 'close':
                return "{}が閉まりました".format(device_name)
            elif open_state == 'timeOutNotClose':
                return "{}が長時間開いたままです！".format(device_name)
            else:
                return "{}の状態: {}".format(device_name, open_state)

        # Motion Sensor
        if device_type == 'Motion Sensor':
            detected = status.get('moveDetected', False)
            if detected:
                return "{}が動きを検知しました".format(device_name)
            else:
                return "{}の動き検知がクリアされました".format(device_name)

        # Video Doorbell
        if device_type == 'Video Doorbell':
            return "{}が押されました".format(device_name)

        # Default
        return "{}の状態が変わりました".format(device_name)

    def notify_security_event(self, device_name, device_type, status):
        """
        Send security event notification to #home-security channel.

        Args:
            device_name: Device name
            device_type: Device type
            status: Current status dict

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        message_ja = self._get_security_message_ja(device_name, device_type, status)

        # Determine emoji based on event type
        emoji = ""
        if 'Lock' in device_type:
            lock_state = status.get('lockState', '')
            emoji = "" if lock_state == 'locked' else ""
        elif device_type == 'Contact Sensor':
            open_state = status.get('openState', '')
            emoji = "" if open_state == 'open' else ""
        elif device_type == 'Motion Sensor':
            emoji = ""
        elif device_type == 'Video Doorbell':
            emoji = ""

        text = "{} {}".format(emoji, message_ja)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*{} {}*".format(emoji, message_ja)
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "{} | {}".format(device_type, timestamp)
                    }
                ]
            }
        ]

        return self._send_to_channel('home_security', text, blocks)

    def notify_atmos_update(self, device_name, device_type, status):
        """
        Send atmosphere sensor update to #atmos-update channel.

        Args:
            device_name: Device name
            device_type: Device type
            status: Current status dict

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Build status summary
        summaries = []
        if 'temperature' in status:
            summaries.append("{}°C".format(status['temperature']))
        if 'humidity' in status:
            summaries.append("{}%".format(status['humidity']))
        if 'CO2' in status:
            summaries.append("{}ppm".format(status['CO2']))

        status_text = " / ".join(summaries) if summaries else "No data"
        text = "[{}] {}".format(device_name, status_text)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*{}*\n{}".format(device_name, status_text)
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "{} | {}".format(device_type, timestamp)
                    }
                ]
            }
        ]

        return self._send_to_channel('atmos_update', text, blocks)

    def notify_atmos_graph(self, date_str, devices_data, chart_urls):
        """
        Send atmosphere graph to #atmos-graph channel.

        Args:
            date_str: Date string (YYYY-MM-DD)
            devices_data: List of device summary dicts (with is_outdoor flag)
            chart_urls: Dict of chart URLs

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%H:%M')

        # Build summary table (separate outdoor and indoor)
        outdoor_lines = []
        indoor_lines = []

        for device in devices_data:
            name = device.get('device_name', 'Unknown')
            temp = device.get('temperature', {}).get('latest', '-')
            humidity = device.get('humidity', {}).get('latest', '-')
            co2 = device.get('co2', {}).get('latest', '-')
            pressure = device.get('pressure', {}).get('latest', '-')
            noise = device.get('noise', {}).get('latest', '-')
            is_outdoor = device.get('is_outdoor', False)

            # Get wind and rain data (only for outdoor sensors)
            module_type = device.get('module_type', '')

            # Wind and rain only apply to specific outdoor modules
            is_wind_module = module_type == 'NAModule2'
            is_rain_module = module_type == 'NAModule3'

            wind_strength = device.get('wind_strength', {}).get('latest', '-') if is_wind_module else '-'
            gust_strength = device.get('gust_strength', {}).get('latest', '-') if is_wind_module else '-'
            rain = device.get('rain', {}).get('latest', '-') if is_rain_module else '-'
            rain_24h = device.get('rain_24h', {}).get('latest', '-') if is_rain_module else '-'

            has_data = any([
                temp != '-', humidity != '-', co2 != '-',
                pressure != '-', noise != '-',
                wind_strength != '-', rain != '-'
            ])

            if has_data:
                parts = []
                if temp != '-':
                    if isinstance(temp, (int, float)):
                        parts.append("{:.1f}°C".format(temp))
                    else:
                        parts.append("{}°C".format(temp))
                if humidity != '-':
                    parts.append("{}%".format(humidity))
                if co2 != '-':
                    parts.append("{}ppm".format(co2))
                if pressure != '-':
                    if isinstance(pressure, (int, float)):
                        parts.append("{:.1f}hPa".format(pressure))
                    else:
                        parts.append("{}hPa".format(pressure))
                if noise != '-':
                    parts.append("{}dB".format(noise))
                # Wind data (only for NAModule2)
                if wind_strength != '-':
                    wind_str = "{}km/h".format(wind_strength)
                    if gust_strength != '-':
                        wind_str += " (突風:{}km/h)".format(gust_strength)
                    parts.append(wind_str)
                # Rain data (only for NAModule3)
                if rain_24h != '-':
                    parts.append("{}mm/24h".format(rain_24h))
                elif rain != '-':
                    parts.append("{}mm".format(rain))

                line = "*{}*: {}".format(name, " / ".join(parts))

                if is_outdoor or is_wind_module or is_rain_module:
                    outdoor_lines.append(line)
                else:
                    indoor_lines.append(line)

        # Build summary text
        summary_parts = []
        if outdoor_lines:
            summary_parts.append("*🌳 屋外*\n" + "\n".join(outdoor_lines))
        if indoor_lines:
            summary_parts.append("*🏠 屋内*\n" + "\n".join(indoor_lines))

        summary_text = "\n\n".join(summary_parts) if summary_parts else "No data"

        text = "Atmosphere Report ({} {})".format(date_str, timestamp)

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "環境センサーレポート ({})".format(timestamp),
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": summary_text
                }
            }
        ]

        # Chart titles mapping
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
            # Legacy keys
            'temp_humidity': '温度',
        }

        # Add chart images in specific order
        chart_order = [
            'outdoor_temp', 'outdoor_humidity',
            'indoor_temp', 'indoor_humidity', 'co2',
            'pressure', 'noise',
            'wind', 'wind_direction',
            'rain'
        ]

        if chart_urls:
            for chart_name in chart_order:
                url = chart_urls.get(chart_name)
                if url:
                    chart_title = chart_titles.get(chart_name, chart_name)

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
                    "text": "{}".format(date_str)
                }
            ]
        })

        return self._send_to_channel('atmos_graph', text, blocks)

    def notify_startup(self, device_count, channel='home_security'):
        """
        Send startup notification.

        Args:
            device_count: Number of devices being monitored
            channel: Channel to send to

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        text = "[SwitchBot Monitor] Started monitoring {} devices".format(device_count)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*SwitchBot Monitor Started*\nMonitoring {} devices".format(device_count)
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

        return self._send_to_channel(channel, text, blocks)

    def notify_outdoor_alert(self, alert_type, message, details=None, level='info'):
        """
        Send outdoor weather alert to #outdoor-alert channel.

        Args:
            alert_type: Type of alert ('rain', 'wind', 'temperature', 'pressure')
            message: Main alert message
            details: Optional additional details
            level: Alert level ('info', 'warning', 'danger')

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Emoji and color by alert type
        alert_config = {
            'rain': {'emoji': '', 'color': '#3498db'},
            'wind': {'emoji': '', 'color': '#9b59b6'},
            'temperature_hot': {'emoji': '', 'color': '#e74c3c'},
            'temperature_cold': {'emoji': '', 'color': '#3498db'},
            'pressure_down': {'emoji': '', 'color': '#e67e22'},
            'pressure_up': {'emoji': '', 'color': '#27ae60'},
        }

        # Level indicators
        level_emoji = {
            'info': '',
            'warning': '',
            'danger': ''
        }

        config = alert_config.get(alert_type, {'emoji': '', 'color': '#95a5a6'})
        emoji = config['emoji']
        level_indicator = level_emoji.get(level, '')

        text = "{} {} {}".format(emoji, level_indicator, message) if level != 'info' else "{} {}".format(emoji, message)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*{} {}*".format(emoji, message)
                }
            }
        ]

        if details:
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": details
                    }
                ]
            })

        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "{} | {}".format(level_indicator + ' ' + level.upper() if level != 'info' else 'INFO', timestamp)
                }
            ]
        })

        return self._send_to_channel('outdoor_alert', text, blocks)

    def notify_error(self, error_message, device_name=None, channel='home_security'):
        """
        Send error notification.

        Args:
            error_message: Error description
            device_name: Optional device name if error is device-specific
            channel: Channel to send to

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if device_name:
            text = "[Error] {}: {}".format(device_name, error_message)
        else:
            text = "[Error] {}".format(error_message)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Error*\n```{}```".format(error_message)
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
            blocks[0]['text']['text'] = "*Error* ({})\n```{}```".format(device_name, error_message)

        return self._send_to_channel(channel, text, blocks)


if __name__ == '__main__':
    # Simple test (won't actually send without valid webhook)
    config = {
        'enabled': False,
        'channels': {
            'home_security': 'https://hooks.slack.com/services/xxx',
            'atmos_update': 'https://hooks.slack.com/services/xxx',
            'atmos_graph': 'https://hooks.slack.com/services/xxx'
        }
    }
    notifier = SlackNotifier(config)

    print("Test: Security message")
    msg = notifier._get_security_message_ja("ロックPro 24", "Smart Lock Pro", {"lockState": "unlocked"})
    print("  -> {}".format(msg))

    msg = notifier._get_security_message_ja("開閉センサー", "Contact Sensor", {"openState": "open"})
    print("  -> {}".format(msg))

    print("Test completed!")
