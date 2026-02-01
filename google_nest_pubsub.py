# -*- coding: utf-8 -*-
"""
Google Nest SDM Pub/Sub client using REST API.
Python 3.7+ compatible, requires only requests library (no grpcio).

Uses long polling to receive real-time events from Google Nest devices.
Reference: https://developers.google.com/nest/device-access/subscribe-to-events
"""
import base64
import json
import logging
import threading
import time
from datetime import datetime

import requests


class GoogleNestPubSubClient:
    """
    Pub/Sub client for receiving Google Nest SDM events via REST API.

    Uses long polling instead of the google-cloud-pubsub library to avoid
    grpcio dependency issues on Raspberry Pi / Python 3.7.
    """

    PUBSUB_API_BASE = "https://pubsub.googleapis.com/v1"
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    # SDM Event types
    EVENT_TYPES = {
        'sdm.devices.events.DoorbellChime.Chime': 'chime',
        'sdm.devices.events.CameraMotion.Motion': 'motion',
        'sdm.devices.events.CameraPerson.Person': 'person',
        'sdm.devices.events.CameraSound.Sound': 'sound',
        'sdm.devices.events.CameraClipPreview.ClipPreview': 'clip_preview',
    }

    def __init__(self, gcp_project_id, subscription_id, client_id, client_secret,
                 refresh_token, device_access_project_id=None, credentials_file=None):
        """
        Initialize Pub/Sub client.

        Args:
            gcp_project_id: Google Cloud project ID (for Pub/Sub)
            subscription_id: Pub/Sub subscription ID
            client_id: OAuth2 client ID
            client_secret: OAuth2 client secret
            refresh_token: OAuth2 refresh token
            device_access_project_id: Device Access project ID (for device name parsing)
            credentials_file: Optional file to persist updated refresh token
        """
        self.gcp_project_id = gcp_project_id
        self.subscription_id = subscription_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.device_access_project_id = device_access_project_id
        self.credentials_file = credentials_file

        self.access_token = None
        self.token_expires_at = 0

        # Event callback
        self._event_callback = None

        # Thread control
        self._running = False
        self._thread = None

        # Event session tracking (for correlating clip previews with events)
        self._event_sessions = {}  # {eventSessionId: event_data}
        self._session_ttl = 300  # 5 minutes TTL for session data

        # Device name cache (device_id -> device_name)
        self._device_names = {}

    def set_event_callback(self, callback):
        """
        Set callback function for received events.

        Args:
            callback: Function(event_type, device_id, device_name, event_data)
        """
        self._event_callback = callback

    def set_device_names(self, device_map):
        """
        Set device name cache for better event notifications.

        Args:
            device_map: Dict of {device_id: device_name}
        """
        self._device_names = device_map

    def _refresh_access_token(self):
        """Refresh OAuth2 access token."""
        payload = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }

        try:
            response = requests.post(self.TOKEN_URL, data=payload, timeout=30)
            response.raise_for_status()
            data = response.json()

            self.access_token = data['access_token']
            expires_in = data.get('expires_in', 3600)
            self.token_expires_at = time.time() + expires_in - 300  # 5 min buffer

            # Handle new refresh token if provided
            if 'refresh_token' in data and data['refresh_token'] != self.refresh_token:
                self.refresh_token = data['refresh_token']
                logging.info("Pub/Sub refresh token updated")
                self._save_credentials()

            logging.debug("Pub/Sub access token refreshed, expires in %d seconds", expires_in)
            return True

        except requests.exceptions.RequestException as e:
            logging.error("Failed to refresh Pub/Sub access token: %s", e)
            raise

    def _save_credentials(self):
        """Save updated credentials to file."""
        if not self.credentials_file:
            return

        try:
            # Read existing file and update refresh token
            with open(self.credentials_file, 'r') as f:
                credentials = json.load(f)

            credentials['refresh_token'] = self.refresh_token

            with open(self.credentials_file, 'w') as f:
                json.dump(credentials, f, indent=2)

            logging.debug("Pub/Sub credentials saved to %s", self.credentials_file)
        except Exception as e:
            logging.warning("Failed to save Pub/Sub credentials: %s", e)

    def _ensure_valid_token(self):
        """Ensure we have a valid access token."""
        if not self.access_token or time.time() >= self.token_expires_at:
            self._refresh_access_token()

    def download_clip_preview(self, preview_url, output_path=None):
        """
        Download clip preview MP4 from previewUrl.

        Args:
            preview_url: Preview URL from event data
            output_path: Optional path to save file

        Returns:
            bytes or str: MP4 bytes if no output_path, else output_path
        """
        self._ensure_valid_token()

        headers = {
            'Authorization': 'Bearer {}'.format(self.access_token)
        }

        try:
            response = requests.get(preview_url, headers=headers, timeout=30)
            response.raise_for_status()

            if output_path:
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                logging.debug("Downloaded clip preview to %s", output_path)
                return output_path

            return response.content

        except requests.exceptions.RequestException as e:
            logging.error("Failed to download clip preview: %s", e)
            return None

    def _get_subscription_path(self):
        """Get full subscription path."""
        # If subscription_id is already a full path, use it as-is
        if self.subscription_id.startswith("projects/"):
            return self.subscription_id
        return "projects/{}/subscriptions/{}".format(
            self.gcp_project_id, self.subscription_id
        )

    def pull_messages(self, max_messages=10, timeout=60):
        """
        Pull messages from Pub/Sub using long polling.

        Args:
            max_messages: Maximum number of messages to retrieve
            timeout: HTTP timeout in seconds (controls long polling duration)

        Returns:
            list: List of received messages
        """
        self._ensure_valid_token()

        url = "{}/{}:pull".format(self.PUBSUB_API_BASE, self._get_subscription_path())

        headers = {
            'Authorization': 'Bearer {}'.format(self.access_token),
            'Content-Type': 'application/json'
        }

        body = {
            'maxMessages': max_messages,
            'returnImmediately': False  # Enable long polling
        }

        try:
            response = requests.post(
                url,
                headers=headers,
                json=body,
                timeout=timeout + 10  # Add buffer for server-side timeout
            )
            response.raise_for_status()

            data = response.json()
            return data.get('receivedMessages', [])

        except requests.exceptions.Timeout:
            # Timeout is expected when no messages are available
            logging.debug("Pub/Sub pull timeout (no messages)")
            return []

        except requests.exceptions.RequestException as e:
            logging.error("Pub/Sub pull failed: %s", e)
            if hasattr(e, 'response') and e.response is not None:
                logging.error("Response: %s", e.response.text)
            raise

    def acknowledge_messages(self, ack_ids):
        """
        Acknowledge received messages.

        Args:
            ack_ids: List of ack IDs to acknowledge
        """
        if not ack_ids:
            return

        self._ensure_valid_token()

        url = "{}/{}:acknowledge".format(self.PUBSUB_API_BASE, self._get_subscription_path())

        headers = {
            'Authorization': 'Bearer {}'.format(self.access_token),
            'Content-Type': 'application/json'
        }

        body = {
            'ackIds': ack_ids
        }

        try:
            response = requests.post(url, headers=headers, json=body, timeout=30)
            response.raise_for_status()
            logging.debug("Acknowledged %d messages", len(ack_ids))

        except requests.exceptions.RequestException as e:
            logging.warning("Failed to acknowledge messages: %s", e)

    def _parse_message(self, message):
        """
        Parse a Pub/Sub message.

        Args:
            message: Raw message dict from Pub/Sub

        Returns:
            dict: Parsed event data or None
        """
        try:
            # Decode base64 message data
            data_base64 = message.get('message', {}).get('data', '')
            if not data_base64:
                return None

            data_bytes = base64.b64decode(data_base64)
            data = json.loads(data_bytes.decode('utf-8'))

            return data

        except (json.JSONDecodeError, ValueError) as e:
            logging.warning("Failed to parse Pub/Sub message: %s", e)
            return None

    def _extract_device_id(self, resource_name):
        """
        Extract device ID from resource name.

        Args:
            resource_name: Full resource name like "enterprises/project-id/devices/device-id"

        Returns:
            str: Device ID
        """
        if not resource_name:
            return None

        parts = resource_name.split('/')
        if len(parts) >= 4 and parts[2] == 'devices':
            return parts[3]

        return None

    def _get_device_name(self, device_id):
        """Get device name from cache or return device ID."""
        return self._device_names.get(device_id, device_id)

    def _process_event(self, data):
        """
        Process a parsed event message.

        Args:
            data: Parsed event data dict
        """
        resource_update = data.get('resourceUpdate', {})
        events = resource_update.get('events', {})

        if not events:
            # This might be a trait update, not an event
            logging.debug("Received non-event message (trait update): %s", data)
            return

        # Extract device info
        resource_name = resource_update.get('name', '')
        device_id = self._extract_device_id(resource_name)
        device_name = self._get_device_name(device_id)

        timestamp = data.get('timestamp', '')
        event_thread_id = data.get('eventThreadId', '')
        event_thread_state = data.get('eventThreadState', '')

        # Process each event type
        for event_key, event_value in events.items():
            event_type = self.EVENT_TYPES.get(event_key)

            if not event_type:
                logging.debug("Unknown event type: %s", event_key)
                continue

            logging.info(
                "[Pub/Sub] %s event from %s: %s",
                event_type, device_name, event_key
            )

            # Handle clip preview correlation
            event_session_id = event_value.get('eventSessionId')

            if event_type == 'clip_preview':
                # Store clip preview for correlation with other events
                preview_url = event_value.get('previewUrl', '')
                if event_session_id and preview_url:
                    self._event_sessions[event_session_id] = {
                        'preview_url': preview_url,
                        'timestamp': time.time()
                    }
                    logging.debug("Stored clip preview for session %s", event_session_id)
                continue  # Don't send separate notification for clip preview

            # Build event data
            event_data = {
                'event_type': event_type,
                'device_id': device_id,
                'device_name': device_name,
                'timestamp': timestamp,
                'event_thread_id': event_thread_id,
                'event_thread_state': event_thread_state,
                'raw': event_value,
            }

            # Check for associated clip preview
            if event_session_id and event_session_id in self._event_sessions:
                session_data = self._event_sessions[event_session_id]
                event_data['preview_url'] = session_data.get('preview_url')

            # Invoke callback
            if self._event_callback:
                try:
                    self._event_callback(event_type, device_id, device_name, event_data)
                except Exception as e:
                    logging.error("Event callback error: %s", e)

        # Cleanup old sessions
        self._cleanup_sessions()

    def _cleanup_sessions(self):
        """Remove expired event sessions."""
        now = time.time()
        expired = [
            sid for sid, data in self._event_sessions.items()
            if now - data.get('timestamp', 0) > self._session_ttl
        ]
        for sid in expired:
            del self._event_sessions[sid]

    def _poll_loop(self, poll_timeout=60):
        """
        Main polling loop.

        Args:
            poll_timeout: Timeout for each poll request in seconds
        """
        logging.info("Pub/Sub polling loop started (timeout=%ds)", poll_timeout)

        consecutive_errors = 0
        max_backoff = 300  # Max 5 minutes backoff

        while self._running:
            try:
                messages = self.pull_messages(max_messages=10, timeout=poll_timeout)

                if messages:
                    logging.debug("Received %d messages", len(messages))

                    ack_ids = []
                    for msg in messages:
                        ack_id = msg.get('ackId')
                        if ack_id:
                            ack_ids.append(ack_id)

                        # Parse and process message
                        data = self._parse_message(msg)
                        if data:
                            self._process_event(data)

                    # Acknowledge all messages
                    self.acknowledge_messages(ack_ids)

                # Reset error count on success
                consecutive_errors = 0

            except requests.exceptions.RequestException as e:
                consecutive_errors += 1
                backoff = min(2 ** consecutive_errors, max_backoff)
                logging.warning(
                    "Pub/Sub poll error (retry in %ds): %s", backoff, e
                )
                time.sleep(backoff)

            except Exception as e:
                logging.error("Unexpected error in Pub/Sub loop: %s", e)
                consecutive_errors += 1
                backoff = min(2 ** consecutive_errors, max_backoff)
                time.sleep(backoff)

        logging.info("Pub/Sub polling loop stopped")

    def start(self, poll_timeout=60):
        """
        Start the Pub/Sub polling loop in a background thread.

        Args:
            poll_timeout: Timeout for each poll request in seconds
        """
        if self._running:
            logging.warning("Pub/Sub client already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            args=(poll_timeout,),
            daemon=True,
            name="NestPubSubClient"
        )
        self._thread.start()
        logging.info("Pub/Sub client started")

    def stop(self):
        """Stop the Pub/Sub polling loop."""
        if not self._running:
            return

        logging.info("Stopping Pub/Sub client...")
        self._running = False

        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

        logging.info("Pub/Sub client stopped")

    def is_running(self):
        """Check if the polling loop is running."""
        return self._running and self._thread and self._thread.is_alive()


if __name__ == '__main__':
    # Test client
    import sys

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    def event_handler(event_type, device_id, device_name, event_data):
        print("\n=== Event Received ===")
        print("Type: {}".format(event_type))
        print("Device: {} ({})".format(device_name, device_id))
        print("Data: {}".format(json.dumps(event_data, indent=2, ensure_ascii=False)))
        print("=" * 30)

    if len(sys.argv) > 1:
        # Load credentials from file
        with open(sys.argv[1], 'r') as f:
            creds = json.load(f)

        client = GoogleNestPubSubClient(
            gcp_project_id=creds['gcp_project_id'],
            subscription_id=creds['subscription_id'],
            client_id=creds['client_id'],
            client_secret=creds['client_secret'],
            refresh_token=creds['refresh_token'],
            device_access_project_id=creds.get('project_id')
        )

        client.set_event_callback(event_handler)
        client.start(poll_timeout=60)

        print("Listening for Nest events... Press Ctrl+C to stop")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
            client.stop()
    else:
        print("Usage: python google_nest_pubsub.py <credentials_file.json>")
        print("\nCredentials file format:")
        print(json.dumps({
            'gcp_project_id': 'your-gcp-project-id',
            'subscription_id': 'your-subscription-id',
            'client_id': 'your-client-id.apps.googleusercontent.com',
            'client_secret': 'your-client-secret',
            'refresh_token': 'your-refresh-token',
            'project_id': 'your-device-access-project-id'
        }, indent=2))
