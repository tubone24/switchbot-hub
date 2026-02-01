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

    # Google Nest device types
    NEST_DEVICE_TYPES = [
        'Doorbell', 'Camera', 'Display', 'Thermostat'
    ]

    def __init__(self, config):
        """
        Initialize Slack notifier with channel configuration.

        Args:
            config: Slack config dict with 'channels' and other settings
        """
        self.enabled = config.get('enabled', True)
        self.channels = config.get('channels', {})
        self.bot_token = config.get('bot_token')

        # Channel IDs for file uploads (different from webhook URLs)
        self.channel_ids = config.get('channel_ids', {})

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

    def upload_file(self, channel, file_path=None, file_content=None, filename=None,
                    title=None, initial_comment=None):
        """
        Upload a file to Slack channel using Bot Token.

        Args:
            channel: Channel key ('home_security', etc.) or channel ID
            file_path: Path to file to upload
            file_content: File content as bytes (alternative to file_path)
            filename: Filename for the upload
            title: Title for the file
            initial_comment: Comment to add with the file

        Returns:
            bool: True if uploaded successfully
        """
        if not self.enabled:
            return True

        if not self.bot_token:
            print("[Slack] Bot token not configured for file upload")
            return False

        # Get channel ID
        channel_id = self.channel_ids.get(channel, channel)

        headers = {
            'Authorization': 'Bearer {}'.format(self.bot_token)
        }

        try:
            # Step 1: Get upload URL
            if file_path:
                import os
                file_size = os.path.getsize(file_path)
                if not filename:
                    filename = os.path.basename(file_path)
            elif file_content:
                file_size = len(file_content)
                if not filename:
                    filename = 'file'
            else:
                print("[Slack] No file provided")
                return False

            # Get upload URL using files.getUploadURLExternal
            url_response = requests.post(
                'https://slack.com/api/files.getUploadURLExternal',
                headers=headers,
                data={
                    'filename': filename,
                    'length': file_size
                },
                timeout=30
            )
            url_data = url_response.json()

            if not url_data.get('ok'):
                print("[Slack] Failed to get upload URL: {}".format(url_data.get('error')))
                return False

            upload_url = url_data['upload_url']
            file_id = url_data['file_id']

            # Step 2: Upload file to URL
            if file_path:
                with open(file_path, 'rb') as f:
                    upload_response = requests.post(
                        upload_url,
                        files={'file': f},
                        timeout=60
                    )
            else:
                upload_response = requests.post(
                    upload_url,
                    files={'file': (filename, file_content)},
                    timeout=60
                )

            if upload_response.status_code != 200:
                print("[Slack] Failed to upload file: {}".format(upload_response.status_code))
                return False

            # Step 3: Complete upload with files.completeUploadExternal
            complete_response = requests.post(
                'https://slack.com/api/files.completeUploadExternal',
                headers=headers,
                json={
                    'files': [{'id': file_id, 'title': title or filename}],
                    'channel_id': channel_id,
                    'initial_comment': initial_comment or ''
                },
                timeout=30
            )
            complete_data = complete_response.json()

            if not complete_data.get('ok'):
                print("[Slack] Failed to complete upload: {}".format(complete_data.get('error')))
                return False

            return True

        except requests.exceptions.RequestException as e:
            print("[Slack] Failed to upload file: {}".format(e))
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
            lock_state = status.get('lockState', '').lower()
            if lock_state == 'locked':
                return "玄関の鍵が締まりました"
            elif lock_state == 'unlocked':
                return "玄関の鍵が開きました"
            elif lock_state == 'jammed':
                return "玄関のロックがジャム（詰まり）状態です！"
            else:
                return "玄関のロック状態: {}".format(lock_state)

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
            # Check both formats: API status uses 'moveDetected', Webhook uses 'detectionState'
            detection_state = status.get('detectionState', '')
            move_detected = status.get('moveDetected', False)

            if detection_state == 'DETECTED' or move_detected:
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
            emoji = "🔒" if lock_state == 'locked' else "🔓"
        elif device_type == 'Contact Sensor':
            open_state = status.get('openState', '')
            emoji = "🚪" if open_state == 'open' else "✅"
        elif device_type == 'Motion Sensor':
            emoji = "👁️"
        elif device_type == 'Video Doorbell':
            emoji = "🔔"

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
        # Light level (Hub 2: lightLevel as number, Contact/Motion Sensor: brightness as dim/bright)
        if 'lightLevel' in status:
            summaries.append("照度:{}".format(status['lightLevel']))
        elif 'brightness' in status:
            brightness_ja = '明るい' if status['brightness'].lower() == 'bright' else '暗い'
            summaries.append("照度:{}".format(brightness_ja))

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

    def notify_netatmo_update(self, device_name, module_type, is_outdoor, reading):
        """
        Send Netatmo sensor update to #atmos-update channel.

        Args:
            device_name: Device name
            module_type: Netatmo module type (NAMain, NAModule1, etc.)
            is_outdoor: Whether this is an outdoor module
            reading: Sensor reading dict

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Build status summary based on module type
        summaries = []

        # Temperature and humidity (most modules)
        if reading.get('temperature') is not None:
            summaries.append("{:.1f}°C".format(reading['temperature']))
        if reading.get('humidity') is not None:
            summaries.append("{}%".format(reading['humidity']))

        # CO2 (indoor modules)
        if reading.get('co2') is not None:
            summaries.append("{}ppm".format(reading['co2']))

        # Pressure (main station)
        if reading.get('pressure') is not None:
            summaries.append("{:.1f}hPa".format(reading['pressure']))

        # Noise (main station)
        if reading.get('noise') is not None:
            summaries.append("{}dB".format(reading['noise']))

        # Wind (NAModule2) - convert km/h to m/s
        if reading.get('wind_strength') is not None:
            wind_ms = reading['wind_strength'] / 3.6
            wind_str = "風速{:.1f}m/s".format(wind_ms)
            if reading.get('gust_strength') is not None:
                gust_ms = reading['gust_strength'] / 3.6
                wind_str += "(突風{:.1f}m/s)".format(gust_ms)
            if reading.get('wind_angle') is not None:
                direction = self._angle_to_direction(reading['wind_angle'])
                wind_str = "{}{}".format(direction, wind_str)
            summaries.append(wind_str)

        # Rain (NAModule3)
        if reading.get('rain') is not None or reading.get('rain_24h') is not None:
            rain_parts = []
            if reading.get('rain') is not None:
                rain_parts.append("{}mm".format(reading['rain']))
            if reading.get('rain_1h') is not None:
                rain_parts.append("1h:{}mm".format(reading['rain_1h']))
            if reading.get('rain_24h') is not None:
                rain_parts.append("24h:{}mm".format(reading['rain_24h']))
            summaries.append("雨量 " + " / ".join(rain_parts))

        status_text = " / ".join(summaries) if summaries else "No data"

        # Emoji based on location
        emoji = "🌳" if is_outdoor else "🏠"

        # Module type description
        module_desc = {
            'NAMain': '屋内メイン',
            'NAModule1': '屋外',
            'NAModule2': '風速計',
            'NAModule3': '雨量計',
            'NAModule4': '屋内追加'
        }.get(module_type, module_type)

        text = "{} [{}] {}".format(emoji, device_name, status_text)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "{} *{}*\n{}".format(emoji, device_name, status_text)
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Netatmo {} | {}".format(module_desc, timestamp)
                    }
                ]
            }
        ]

        return self._send_to_channel('atmos_update', text, blocks)

    def _angle_to_direction(self, angle):
        """Convert wind angle to compass direction."""
        if angle is None:
            return ''
        directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                      'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
        idx = round(angle / 22.5) % 16
        return directions[idx]

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
                # Wind data (only for NAModule2) - convert km/h to m/s
                if wind_strength != '-':
                    wind_ms = float(wind_strength) / 3.6
                    wind_str = "{:.1f}m/s".format(wind_ms)
                    if gust_strength != '-':
                        gust_ms = float(gust_strength) / 3.6
                        wind_str += " (突風:{:.1f}m/s)".format(gust_ms)
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
            'light_level': '💡 照度',
            # Legacy keys
            'temp_humidity': '温度',
        }

        # Add chart images in specific order
        chart_order = [
            'outdoor_temp', 'outdoor_humidity',
            'indoor_temp', 'indoor_humidity', 'co2',
            'pressure', 'noise',
            'wind', 'wind_direction',
            'rain',
            'light_level'
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

    def notify_nest_doorbell(self, device_name, event_type, event_data=None):
        """
        Send Google Nest doorbell/camera event notification to #home-security channel.

        Args:
            device_name: Device name
            event_type: Event type ('chime', 'motion', 'person', 'sound')
            event_data: Optional event data dict

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Event type to Japanese message and emoji
        event_config = {
            'chime': {
                'emoji': '',
                'message': 'ドアベルが押されました',
                'detail': 'チャイムが鳴りました'
            },
            'motion': {
                'emoji': '',
                'message': '動きを検知しました',
                'detail': 'カメラが動きを検出'
            },
            'person': {
                'emoji': '',
                'message': '人物を検知しました',
                'detail': '人物が検出されました'
            },
            'sound': {
                'emoji': '',
                'message': '音を検知しました',
                'detail': '音声が検出されました'
            },
        }

        config = event_config.get(event_type, {
            'emoji': '',
            'message': 'イベントが発生しました',
            'detail': event_type
        })

        emoji = config['emoji']
        message = config['message']

        text = "{} [{}] {}".format(emoji, device_name, message)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*{} {}*\n{}".format(emoji, message, device_name)
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Google Nest {} | {}".format(
                            'Doorbell' if event_type == 'chime' else 'Camera',
                            timestamp
                        )
                    }
                ]
            }
        ]

        # Add image if available in event_data
        if event_data and event_data.get('image_url'):
            blocks.insert(1, {
                "type": "image",
                "image_url": event_data['image_url'],
                "alt_text": "{} - {}".format(device_name, message)
            })

        return self._send_to_channel('home_security', text, blocks)

    def notify_nest_camera_event(self, device_name, event_type, zone_name=None, clip_url=None):
        """
        Send Google Nest camera event notification.

        Args:
            device_name: Camera device name
            event_type: Event type ('motion', 'person', 'sound')
            zone_name: Optional activity zone name
            clip_url: Optional clip preview URL

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        event_config = {
            'motion': {'emoji': '', 'message': '動きを検知'},
            'person': {'emoji': '', 'message': '人物を検知'},
            'sound': {'emoji': '', 'message': '音を検知'},
        }

        config = event_config.get(event_type, {'emoji': '', 'message': event_type})
        emoji = config['emoji']
        message = config['message']

        location_text = ''
        if zone_name:
            location_text = ' ({})'.format(zone_name)

        text = "{} [{}] {}{}".format(emoji, device_name, message, location_text)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*{} {}{}*\n{}".format(emoji, message, location_text, device_name)
                }
            }
        ]

        # Add clip link if available
        if clip_url:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "<{}|クリップを見る>".format(clip_url)
                }
            })

        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Google Nest Camera | {}".format(timestamp)
                }
            ]
        })

        return self._send_to_channel('home_security', text, blocks)

    def notify_nest_device_status(self, device_name, device_type, status):
        """
        Send Google Nest device status update.

        Args:
            device_name: Device name
            device_type: Device type ('Doorbell', 'Camera')
            status: Status dict with connectivity info

        Returns:
            bool: True if sent successfully
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        connectivity = status.get('connectivity_status', 'UNKNOWN')

        if connectivity == 'OFFLINE':
            emoji = ''
            message = 'オフラインになりました'
        elif connectivity == 'ONLINE':
            emoji = ''
            message = 'オンラインに復帰しました'
        else:
            emoji = ''
            message = '状態: {}'.format(connectivity)

        text = "{} [{}] {}".format(emoji, device_name, message)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*{} {}*\n{}".format(emoji, message, device_name)
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Google Nest {} | {}".format(device_type, timestamp)
                    }
                ]
            }
        ]

        return self._send_to_channel('home_security', text, blocks)

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
