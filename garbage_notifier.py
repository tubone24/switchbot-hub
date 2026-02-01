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
        self.monthly_schedule = config.get('monthly_schedule', {})
        self.additional_rules = config.get('additional_rules', {})
        self.slack = slack_notifier

        # Notification times (default: 20:00 for evening, 6:00 for morning)
        self.evening_hour = config.get('evening_hour', 20)
        self.morning_hour = config.get('morning_hour', 6)

        # Make image_dir absolute if relative
        if self.image_dir and not os.path.isabs(self.image_dir):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.image_dir = os.path.join(script_dir, self.image_dir)

    def get_week_of_month(self, target_date):
        """
        Get the week number of the month for a specific date.

        For example, if target_date is the 2nd Sunday of the month, returns 2.

        Args:
            target_date: datetime.date object

        Returns:
            int: Week number (1-5) of the month for that weekday
        """
        # Count how many times this weekday has occurred in the month
        weekday = target_date.weekday()
        count = 0
        day = target_date.replace(day=1)

        while day <= target_date:
            if day.weekday() == weekday:
                count += 1
            day += timedelta(days=1)

        return count

    def get_monthly_garbage_types(self, target_date):
        """
        Get garbage types from monthly schedule for a specific date.

        Args:
            target_date: datetime.date object

        Returns:
            list: List of garbage types scheduled for that day
        """
        if not self.monthly_schedule:
            return []

        result = []
        weekday = target_date.weekday()
        weekday_name = self.WEEKDAY_NAMES[weekday]
        week_of_month = self.get_week_of_month(target_date)

        for garbage_type, rule in self.monthly_schedule.items():
            rule_weekday = rule.get('weekday', '').lower()
            rule_weeks = rule.get('weeks', [])

            # Check if weekday matches
            if rule_weekday != weekday_name:
                continue

            # Check if week number matches
            if week_of_month in rule_weeks:
                result.append(garbage_type)

        return result

    def get_garbage_type(self, target_date):
        """
        Get garbage type for a specific date.

        Args:
            target_date: datetime.date object

        Returns:
            str: Garbage type for that day (weekly schedule only)
        """
        weekday = target_date.weekday()
        weekday_name = self.WEEKDAY_NAMES[weekday]
        return self.schedule.get(weekday_name, 'なし')

    def get_all_garbage_types(self, target_date):
        """
        Get all garbage types for a specific date (weekly + monthly).

        Args:
            target_date: datetime.date object

        Returns:
            list: List of all garbage types for that day
        """
        result = []

        # Get weekly schedule
        weekly_type = self.get_garbage_type(target_date)
        if weekly_type and weekly_type != 'なし':
            result.append(weekly_type)

        # Get monthly schedule
        monthly_types = self.get_monthly_garbage_types(target_date)
        result.extend(monthly_types)

        return result

    def get_additional_items(self, garbage_type):
        """
        Get additional items collected on the same day.

        Args:
            garbage_type: Main garbage type

        Returns:
            list: Additional items or empty list
        """
        return self.additional_rules.get(garbage_type, [])

    def get_image_path_by_name(self, garbage_type):
        """
        Get image file path by garbage type name.

        Args:
            garbage_type: Garbage type name (e.g., '古紙・段ボール')

        Returns:
            str: Full path to image file, or None if not found
        """
        if not self.image_dir or not garbage_type:
            return None

        # Try common image extensions
        for ext in ['.png', '.jpg', '.jpeg', '.gif']:
            path = os.path.join(self.image_dir, garbage_type + ext)
            if os.path.exists(path):
                return path

        return None

    def get_image_path(self, target_date, garbage_type=None):
        """
        Get image file path for the garbage type or weekday.

        Priority:
        1. Image by garbage type name (e.g., '古紙・段ボール.png')
        2. Image by weekday (e.g., '月.png')

        Args:
            target_date: datetime.date object
            garbage_type: Optional garbage type name to search for

        Returns:
            str: Full path to image file, or None if not found
        """
        if not self.image_dir:
            return None

        # First, try to find image by garbage type name
        if garbage_type:
            path = self.get_image_path_by_name(garbage_type)
            if path:
                return path

        # Fallback: try to find image by weekday
        weekday = target_date.weekday()
        weekday_ja = self.WEEKDAY_NAMES_JA[weekday]

        # Try common image extensions
        for ext in ['.png', '.jpg', '.jpeg', '.gif']:
            path = os.path.join(self.image_dir, weekday_ja + ext)
            if os.path.exists(path):
                return path

        logging.warning("Garbage image not found for type '%s' or weekday '%s'",
                        garbage_type, weekday_ja)
        return None

    def build_message(self, garbage_type, is_tomorrow=False):
        """
        Build notification message for a single garbage type.

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

    def build_combined_message(self, garbage_types, is_tomorrow=False):
        """
        Build notification message for multiple garbage types.

        Args:
            garbage_types: List of garbage types
            is_tomorrow: True if this is for tomorrow (evening notification)

        Returns:
            str: Formatted message
        """
        if not garbage_types:
            if is_tomorrow:
                return "明日のゴミ収集はありません"
            else:
                return "今日のゴミ収集はありません"

        # Build main message
        type_list = '、'.join(['「{}」'.format(t) for t in garbage_types])

        if is_tomorrow:
            message = "明日は{}の日です".format(type_list)
        else:
            message = "今日は{}の日です".format(type_list)

        # Collect all additional items
        all_additional = []
        for garbage_type in garbage_types:
            additional = self.get_additional_items(garbage_type)
            all_additional.extend(additional)

        # Remove duplicates while preserving order
        seen = set()
        unique_additional = []
        for item in all_additional:
            if item not in seen:
                seen.add(item)
                unique_additional.append(item)

        if unique_additional:
            message += "\n（{}も収集日です）".format('、'.join(unique_additional))

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

        # Get all garbage types (weekly + monthly)
        garbage_types = self.get_all_garbage_types(target_date)
        logging.info("Garbage types for %s: %s", target_date, garbage_types)

        # Skip notification if no garbage collection
        if not garbage_types:
            logging.info("No garbage collection on %s, skipping notification", target_date)
            return True

        # Build combined message
        message = self.build_combined_message(garbage_types, is_tomorrow)

        # Try to find images for each garbage type
        # Priority: type-specific image > weekday image
        images_to_send = []
        for garbage_type in garbage_types:
            image_path = self.get_image_path(target_date, garbage_type)
            if image_path and image_path not in [img[0] for img in images_to_send]:
                images_to_send.append((image_path, garbage_type))

        # If no type-specific images, try weekday image
        if not images_to_send:
            weekday_image = self.get_image_path(target_date, None)
            if weekday_image:
                images_to_send.append((weekday_image, '、'.join(garbage_types)))

        # Send to Slack
        if images_to_send:
            success = True
            # Send first image with the main message
            first_image, first_title = images_to_send[0]
            result = self.slack.upload_file(
                channel=self.channel_id,
                file_path=first_image,
                filename=os.path.basename(first_image),
                title=first_title,
                initial_comment=message
            )
            if result:
                logging.info("Sent garbage notification with image: %s", first_title)
            else:
                logging.error("Failed to send garbage notification with image")
                success = False

            # Send additional images without message
            for image_path, title in images_to_send[1:]:
                result = self.slack.upload_file(
                    channel=self.channel_id,
                    file_path=image_path,
                    filename=os.path.basename(image_path),
                    title=title,
                    initial_comment=""
                )
                if result:
                    logging.info("Sent additional garbage image: %s", title)
                else:
                    logging.error("Failed to send additional garbage image: %s", title)
                    success = False

            return success
        else:
            # Send text-only message (fallback)
            logging.warning("No image found, sending text-only notification")
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
        Check if it's time for evening notification.

        Args:
            now: datetime object (for testing)

        Returns:
            bool: True if it's the configured evening hour
        """
        if now is None:
            now = datetime.now()
        return now.hour == self.evening_hour and now.minute == 0

    def should_notify_morning(self, now=None):
        """
        Check if it's time for morning notification.

        Args:
            now: datetime object (for testing)

        Returns:
            bool: True if it's the configured morning hour
        """
        if now is None:
            now = datetime.now()
        return now.hour == self.morning_hour and now.minute == 0


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
        },
        'monthly_schedule': {
            '古紙・段ボール': {
                'weekday': 'sunday',
                'weeks': [2, 4]
            },
            '粗大ごみ': {
                'weekday': 'saturday',
                'weeks': [1]
            }
        }
    }

    # Mock slack notifier
    class MockSlack:
        bot_token = 'test'
        def upload_file(self, **kwargs):
            print("Would upload:", kwargs)
            return True

    notifier = GarbageNotifier(config, MockSlack())

    # Test for each day of a week
    from datetime import date
    print("=== Weekly schedule test ===")
    for i in range(7):
        test_date = date(2025, 1, 6 + i)  # Monday Jan 6, 2025
        garbage_type = notifier.get_garbage_type(test_date)
        additional = notifier.get_additional_items(garbage_type)
        print("{}: {} {}".format(
            test_date.strftime('%A'),
            garbage_type,
            "(+" + ', '.join(additional) + ")" if additional else ""
        ))

    # Test monthly schedule (Sundays in January 2025)
    print("\n=== Monthly schedule test (Sundays in Jan 2025) ===")
    sundays = [date(2025, 1, 5), date(2025, 1, 12), date(2025, 1, 19), date(2025, 1, 26)]
    for sunday in sundays:
        week_num = notifier.get_week_of_month(sunday)
        monthly_types = notifier.get_monthly_garbage_types(sunday)
        all_types = notifier.get_all_garbage_types(sunday)
        print("Jan {}: 第{}日曜 - monthly: {}, all: {}".format(
            sunday.day, week_num, monthly_types, all_types
        ))

    # Test monthly schedule (Saturdays in January 2025)
    print("\n=== Monthly schedule test (Saturdays in Jan 2025) ===")
    saturdays = [date(2025, 1, 4), date(2025, 1, 11), date(2025, 1, 18), date(2025, 1, 25)]
    for saturday in saturdays:
        week_num = notifier.get_week_of_month(saturday)
        monthly_types = notifier.get_monthly_garbage_types(saturday)
        print("Jan {}: 第{}土曜 - monthly: {}".format(
            saturday.day, week_num, monthly_types
        ))

    # Test combined message
    print("\n=== Combined message test ===")
    test_date = date(2025, 1, 12)  # 2nd Sunday
    all_types = notifier.get_all_garbage_types(test_date)
    message = notifier.build_combined_message(all_types, is_tomorrow=True)
    print("Types: {}".format(all_types))
    print("Message: {}".format(message))
