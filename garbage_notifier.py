# -*- coding: utf-8 -*-
"""
Garbage collection notification module.
Sends garbage collection reminders to Slack with images.
"""
import os
import logging
from datetime import datetime, timedelta


class GarbageNotifier:
    """Send garbage collection reminders to Slack."""

    # Day of week mapping (Python's weekday(): Monday=0, Sunday=6)
    WEEKDAY_NAMES = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

    # Japanese weekday names for image files
    WEEKDAY_NAMES_JA = ['月', '火', '水', '木', '金', '土', '日']

    def __init__(self, config, slack_notifier):
        """
        Initialize garbage notifier.

        Args:
            config: Garbage collection config dict
            slack_notifier: SlackNotifier instance
        """
        self.enabled = config.get('enabled', False)
        self.channel_id = config.get('channel_id')
        self.image_dir = config.get('image_dir', 'garbage_images')
        self.schedule = config.get('schedule', {})
        self.additional_rules = config.get('additional_rules', {})
        self.slack = slack_notifier

        # Make image_dir absolute if relative
        if self.image_dir and not os.path.isabs(self.image_dir):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.image_dir = os.path.join(script_dir, self.image_dir)

    def get_garbage_type(self, target_date):
        """
        Get garbage type for a specific date.

        Args:
            target_date: datetime.date object

        Returns:
            str: Garbage type for that day
        """
        weekday = target_date.weekday()
        weekday_name = self.WEEKDAY_NAMES[weekday]
        return self.schedule.get(weekday_name, 'なし')

    def get_additional_items(self, garbage_type):
        """
        Get additional items collected on the same day.

        Args:
            garbage_type: Main garbage type

        Returns:
            list: Additional items or empty list
        """
        return self.additional_rules.get(garbage_type, [])

    def get_image_path(self, target_date):
        """
        Get image file path for the target date's weekday.

        Args:
            target_date: datetime.date object

        Returns:
            str: Full path to image file, or None if not found
        """
        if not self.image_dir:
            return None

        # Get Japanese weekday name (月, 火, 水, etc.)
        weekday = target_date.weekday()
        weekday_ja = self.WEEKDAY_NAMES_JA[weekday]

        # Try common image extensions
        for ext in ['.png', '.jpg', '.jpeg', '.gif']:
            path = os.path.join(self.image_dir, weekday_ja + ext)
            if os.path.exists(path):
                return path

        logging.warning("Garbage image not found for weekday: %s", weekday_ja)
        return None

    def build_message(self, garbage_type, is_tomorrow=False):
        """
        Build notification message.

        Args:
            garbage_type: Main garbage type
            is_tomorrow: True if this is for tomorrow (evening notification)

        Returns:
            str: Formatted message
        """
        if garbage_type == 'なし':
            if is_tomorrow:
                return "明日のゴミ収集はありません"
            else:
                return "今日のゴミ収集はありません"

        # Build message with additional items
        additional = self.get_additional_items(garbage_type)

        if is_tomorrow:
            message = "明日は「{}」の日です".format(garbage_type)
        else:
            message = "今日は「{}」の日です".format(garbage_type)

        if additional:
            message += "\n（{}も収集日です）".format('、'.join(additional))

        return message

    def send_notification(self, is_tomorrow=False):
        """
        Send garbage collection notification.

        Args:
            is_tomorrow: True for evening notification (about tomorrow)

        Returns:
            bool: True if sent successfully
        """
        if not self.enabled:
            logging.debug("Garbage notification disabled")
            return True

        if not self.channel_id:
            logging.warning("Garbage notification channel_id not configured")
            return False

        # Determine target date
        now = datetime.now()
        if is_tomorrow:
            target_date = (now + timedelta(days=1)).date()
        else:
            target_date = now.date()

        # Get garbage type
        garbage_type = self.get_garbage_type(target_date)
        logging.info("Garbage type for %s: %s", target_date, garbage_type)

        # Skip notification if no garbage collection
        if garbage_type == 'なし':
            logging.info("No garbage collection on %s, skipping notification", target_date)
            return True

        # Build message
        message = self.build_message(garbage_type, is_tomorrow)

        # Get image (based on weekday)
        image_path = self.get_image_path(target_date)

        # Send to Slack
        if image_path:
            # Upload image with message
            success = self.slack.upload_file(
                channel=self.channel_id,
                file_path=image_path,
                filename=os.path.basename(image_path),
                title=garbage_type,
                initial_comment=message
            )
            if success:
                logging.info("Sent garbage notification with image: %s", garbage_type)
            else:
                logging.error("Failed to send garbage notification with image")
            return success
        else:
            # Send text-only message (fallback)
            logging.warning("No image found, sending text-only notification")
            # Use webhook to send text message
            return self._send_text_message(message)

    def _send_text_message(self, message):
        """
        Send text-only message as fallback.

        Args:
            message: Message text

        Returns:
            bool: True if sent successfully
        """
        # Use Slack's chat.postMessage API
        import requests

        if not self.slack.bot_token:
            logging.error("Bot token not configured for text message")
            return False

        headers = {
            'Authorization': 'Bearer {}'.format(self.slack.bot_token),
            'Content-Type': 'application/json'
        }

        payload = {
            'channel': self.channel_id,
            'text': message,
            'blocks': [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": message
                    }
                }
            ]
        }

        try:
            response = requests.post(
                'https://slack.com/api/chat.postMessage',
                headers=headers,
                json=payload,
                timeout=10
            )
            data = response.json()
            if not data.get('ok'):
                logging.error("Failed to send text message: %s", data.get('error'))
                return False
            return True
        except Exception as e:
            logging.error("Error sending text message: %s", e)
            return False

    def should_notify_evening(self, now=None):
        """
        Check if it's time for evening notification (20:00).

        Args:
            now: datetime object (for testing)

        Returns:
            bool: True if it's 20:00
        """
        if now is None:
            now = datetime.now()
        return now.hour == 20 and now.minute == 0

    def should_notify_morning(self, now=None):
        """
        Check if it's time for morning notification (6:00).

        Args:
            now: datetime object (for testing)

        Returns:
            bool: True if it's 6:00
        """
        if now is None:
            now = datetime.now()
        return now.hour == 6 and now.minute == 0


if __name__ == '__main__':
    # Simple test
    logging.basicConfig(level=logging.DEBUG)

    config = {
        'enabled': True,
        'channel_id': 'C01234567',
        'image_dir': 'garbage_images',
        'schedule': {
            'monday': '燃やすごみ',
            'tuesday': 'プラスチック資源',
            'wednesday': 'なし',
            'thursday': '缶・びん・ペットボトル',
            'friday': '燃やすごみ',
            'saturday': 'なし',
            'sunday': 'なし',
        }
    }

    # Mock slack notifier
    class MockSlack:
        bot_token = 'test'
        def upload_file(self, **kwargs):
            print("Would upload:", kwargs)
            return True

    notifier = GarbageNotifier(config, MockSlack())

    # Test for each day
    from datetime import date
    for i in range(7):
        test_date = date(2025, 1, 6 + i)  # Monday Jan 6, 2025
        garbage_type = notifier.get_garbage_type(test_date)
        additional = notifier.get_additional_items(garbage_type)
        print("{}: {} {}".format(
            test_date.strftime('%A'),
            garbage_type,
            "(+" + ', '.join(additional) + ")" if additional else ""
        ))
