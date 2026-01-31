# -*- coding: utf-8 -*-
"""
Google Nest SDM API client.
Python 3.7+ compatible, requires only requests library.

OAuth2 authentication with refresh token flow.
Reference: https://developers.google.com/nest/device-access/api
"""
import json
import os
import time
import logging
from datetime import datetime

import requests


class GoogleNestAPI:
    """Google Nest SDM API client with OAuth2 authentication."""

    TOKEN_URL = "https://oauth2.googleapis.com/token"
    API_BASE = "https://smartdevicemanagement.googleapis.com/v1"

    # Device types
    DEVICE_TYPES = {
        'sdm.devices.types.DOORBELL': 'Doorbell',
        'sdm.devices.types.CAMERA': 'Camera',
        'sdm.devices.types.DISPLAY': 'Display',
        'sdm.devices.types.THERMOSTAT': 'Thermostat',
    }

    # Event trait types for cameras/doorbells
    EVENT_TRAITS = {
        'sdm.devices.traits.DoorbellChime': 'chime',
        'sdm.devices.traits.CameraMotion': 'motion',
        'sdm.devices.traits.CameraPerson': 'person',
        'sdm.devices.traits.CameraSound': 'sound',
    }

    def __init__(self, project_id, client_id, client_secret, refresh_token, credentials_file=None):
        """
        Initialize Google Nest API client.

        Args:
            project_id: Device Access project ID (UUID format)
            client_id: Google Cloud OAuth2 client ID
            client_secret: Google Cloud OAuth2 client secret
            refresh_token: OAuth2 refresh token
            credentials_file: Optional file path to persist updated refresh token
        """
        self.project_id = project_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.credentials_file = credentials_file

        self.access_token = None
        self.token_expires_at = 0

        # Cache for device states (to detect changes)
        self._device_states = {}
        # Cache for last event timestamps (to avoid duplicate notifications)
        self._last_event_times = {}

    def _refresh_access_token(self):
        """
        Refresh the access token using the refresh token.
        Updates self.access_token and self.token_expires_at.
        """
        payload = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }

        try:
            response = requests.post(
                self.TOKEN_URL,
                data=payload,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            self.access_token = data['access_token']
            expires_in = data.get('expires_in', 3600)  # Default 1 hour
            self.token_expires_at = time.time() + expires_in - 300  # 5 min buffer

            # Google typically doesn't return a new refresh token, but handle it if it does
            if 'refresh_token' in data and data['refresh_token'] != self.refresh_token:
                self.refresh_token = data['refresh_token']
                logging.info("Google Nest refresh token updated")

                if self.credentials_file:
                    self._save_credentials()

            logging.debug("Google Nest access token refreshed, expires in %d seconds", expires_in)
            return True

        except requests.exceptions.RequestException as e:
            logging.error("Failed to refresh Google Nest access token: %s", e)
            if hasattr(e, 'response') and e.response is not None:
                logging.error("Response: %s", e.response.text)
            raise

    def _save_credentials(self):
        """Save updated credentials to file."""
        if not self.credentials_file:
            return

        try:
            credentials = {
                'project_id': self.project_id,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'refresh_token': self.refresh_token
            }
            with open(self.credentials_file, 'w') as f:
                json.dump(credentials, f, indent=2)
            logging.debug("Google Nest credentials saved to %s", self.credentials_file)
        except Exception as e:
            logging.warning("Failed to save Google Nest credentials: %s", e)

    def _ensure_valid_token(self):
        """Ensure we have a valid access token, refreshing if needed."""
        if not self.access_token or time.time() >= self.token_expires_at:
            self._refresh_access_token()

    def _api_request(self, method, endpoint, params=None, data=None):
        """
        Make an authenticated API request.

        Args:
            method: HTTP method (GET, POST)
            endpoint: API endpoint path (e.g., '/devices')
            params: Optional query parameters
            data: Optional request body for POST

        Returns:
            dict: Response body
        """
        self._ensure_valid_token()

        url = "{}/enterprises/{}{}".format(self.API_BASE, self.project_id, endpoint)
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': 'Bearer {}'.format(self.access_token)
        }

        try:
            if method.upper() == 'GET':
                response = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=30
                )
            elif method.upper() == 'POST':
                response = requests.post(
                    url,
                    headers=headers,
                    json=data,
                    timeout=30
                )
            else:
                raise ValueError("Unsupported HTTP method: {}".format(method))

            response.raise_for_status()

            # Some commands return empty response
            if response.text:
                return response.json()
            return {}

        except requests.exceptions.RequestException as e:
            logging.error("Google Nest API request failed: %s", e)
            if hasattr(e, 'response') and e.response is not None:
                logging.error("Response: %s", e.response.text)
            raise

    def get_devices(self):
        """
        Get list of all Nest devices.

        Returns:
            list: List of device dicts
        """
        response = self._api_request('GET', '/devices')
        return response.get('devices', [])

    def get_device(self, device_id):
        """
        Get specific device information.

        Args:
            device_id: Full device ID path

        Returns:
            dict: Device data
        """
        # Device ID is already full path like "enterprises/project-id/devices/device-id"
        # Extract just the device part
        if device_id.startswith('enterprises/'):
            parts = device_id.split('/')
            device_id = parts[-1]

        return self._api_request('GET', '/devices/{}'.format(device_id))

    def get_camera_devices(self):
        """
        Get list of camera and doorbell devices.

        Returns:
            list: List of camera/doorbell devices with parsed info
        """
        devices = self.get_devices()
        camera_devices = []

        for device in devices:
            device_type = device.get('type', '')

            # Filter for cameras and doorbells
            if device_type in ['sdm.devices.types.DOORBELL', 'sdm.devices.types.CAMERA']:
                traits = device.get('traits', {})
                parent_relations = device.get('parentRelations', [])

                # Get display name from parent relations
                display_name = 'Unknown'
                room_name = None
                for relation in parent_relations:
                    if 'displayName' in relation:
                        display_name = relation['displayName']
                        room_name = display_name
                        break

                # Get device custom name from Info trait
                info_trait = traits.get('sdm.devices.traits.Info', {})
                custom_name = info_trait.get('customName', '')
                if custom_name:
                    display_name = custom_name

                # Extract device ID
                device_name = device.get('name', '')
                device_id = device_name.split('/')[-1] if device_name else ''

                camera_devices.append({
                    'device_id': device_id,
                    'device_name': display_name,
                    'device_full_name': device_name,
                    'device_type': self.DEVICE_TYPES.get(device_type, device_type),
                    'device_type_raw': device_type,
                    'room_name': room_name,
                    'traits': traits,
                    'is_doorbell': device_type == 'sdm.devices.types.DOORBELL',
                    'has_motion': 'sdm.devices.traits.CameraMotion' in traits,
                    'has_person': 'sdm.devices.traits.CameraPerson' in traits,
                    'has_sound': 'sdm.devices.traits.CameraSound' in traits,
                    'has_chime': 'sdm.devices.traits.DoorbellChime' in traits,
                })

        return camera_devices

    def execute_command(self, device_id, command, params=None):
        """
        Execute a command on a device.

        Args:
            device_id: Device ID (short or full path)
            command: Command name (e.g., 'sdm.devices.commands.CameraLiveStream.GenerateRtspStream')
            params: Optional command parameters

        Returns:
            dict: Command response
        """
        if device_id.startswith('enterprises/'):
            parts = device_id.split('/')
            device_id = parts[-1]

        data = {
            'command': command,
            'params': params or {}
        }

        return self._api_request('POST', '/devices/{}:executeCommand'.format(device_id), data=data)

    def generate_event_image(self, device_id, event_id):
        """
        Generate a downloadable image from an event.

        Args:
            device_id: Device ID
            event_id: Event ID from the event notification

        Returns:
            dict: Response with 'url' and 'token' for image download
        """
        response = self.execute_command(
            device_id,
            'sdm.devices.commands.CameraEventImage.GenerateImage',
            {'eventId': event_id}
        )
        return response.get('results', {})

    def download_event_image(self, image_url, image_token, output_path=None):
        """
        Download an event image.

        Args:
            image_url: URL from generate_event_image
            image_token: Token from generate_event_image
            output_path: Optional path to save image

        Returns:
            bytes or str: Image bytes if no output_path, else output_path
        """
        headers = {
            'Authorization': 'Basic {}'.format(image_token)
        }

        try:
            response = requests.get(image_url, headers=headers, timeout=30)
            response.raise_for_status()

            if output_path:
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return output_path

            return response.content

        except requests.exceptions.RequestException as e:
            logging.error("Failed to download event image: %s", e)
            raise

    def get_clip_preview_url(self, device_id, event_id):
        """
        Get clip preview URL for an event (if available).

        Note: Clip previews are only available for certain event types
        and require Nest Aware subscription.

        Args:
            device_id: Device ID
            event_id: Event ID

        Returns:
            str or None: Preview URL if available
        """
        # Clip previews come directly from the event data
        # This method is for reference; actual clip URLs come from Pub/Sub events
        return None

    def check_device_events(self):
        """
        Check all camera/doorbell devices for recent events.

        Note: This is a polling-based approach. For real-time events,
        use Google Cloud Pub/Sub subscription.

        Returns:
            list: List of detected events
        """
        events = []
        devices = self.get_camera_devices()

        for device in devices:
            device_id = device['device_id']
            device_name = device['device_name']
            traits = device.get('traits', {})

            # Check each event trait for recent activity
            for trait_name, event_type in self.EVENT_TRAITS.items():
                if trait_name in traits:
                    trait_data = traits[trait_name]

                    # Events have a timestamp in the trait
                    # Note: The API doesn't provide real-time events via polling
                    # This is for initial state detection
                    events.append({
                        'device_id': device_id,
                        'device_name': device_name,
                        'event_type': event_type,
                        'is_doorbell': device['is_doorbell'],
                        'trait_data': trait_data
                    })

        return events

    def get_device_status(self, device_id):
        """
        Get current status of a camera/doorbell device.

        Args:
            device_id: Device ID

        Returns:
            dict: Device status including traits
        """
        device = self.get_device(device_id)
        traits = device.get('traits', {})

        status = {
            'device_id': device_id,
            'online': True,  # Assume online if we can fetch data
            'device_type': device.get('type', ''),
        }

        # Parse relevant traits
        info = traits.get('sdm.devices.traits.Info', {})
        status['custom_name'] = info.get('customName', '')

        # Connectivity (if available)
        connectivity = traits.get('sdm.devices.traits.Connectivity', {})
        status['connectivity_status'] = connectivity.get('status', 'UNKNOWN')

        # Camera-specific traits
        if 'sdm.devices.traits.CameraLiveStream' in traits:
            stream_trait = traits['sdm.devices.traits.CameraLiveStream']
            status['max_video_resolution'] = stream_trait.get('maxVideoResolution', {})
            status['video_codecs'] = stream_trait.get('videoCodecs', [])
            status['audio_codecs'] = stream_trait.get('audioCodecs', [])
            status['supported_protocols'] = stream_trait.get('supportedProtocols', [])

        return status

    def poll_all_devices(self):
        """
        Poll all camera/doorbell devices and return their current state.

        Returns:
            list: List of device states
        """
        devices = self.get_camera_devices()
        results = []

        for device in devices:
            try:
                status = self.get_device_status(device['device_id'])
                status.update({
                    'device_name': device['device_name'],
                    'room_name': device.get('room_name'),
                    'is_doorbell': device['is_doorbell'],
                    'has_motion': device['has_motion'],
                    'has_person': device['has_person'],
                    'has_sound': device['has_sound'],
                    'has_chime': device['has_chime'],
                })
                results.append(status)
            except Exception as e:
                logging.error("Error polling Nest device %s: %s", device['device_name'], e)
                results.append({
                    'device_id': device['device_id'],
                    'device_name': device['device_name'],
                    'online': False,
                    'error': str(e)
                })

        return results


def load_credentials_from_file(filepath):
    """
    Load Google Nest credentials from a JSON file.

    Args:
        filepath: Path to credentials JSON file

    Returns:
        dict: Credentials with project_id, client_id, client_secret, refresh_token
    """
    with open(filepath, 'r') as f:
        return json.load(f)


if __name__ == '__main__':
    # Simple test (requires valid credentials)
    import sys

    logging.basicConfig(level=logging.DEBUG)

    if len(sys.argv) > 1:
        creds = load_credentials_from_file(sys.argv[1])
        api = GoogleNestAPI(
            project_id=creds['project_id'],
            client_id=creds['client_id'],
            client_secret=creds['client_secret'],
            refresh_token=creds['refresh_token']
        )

        print("Fetching devices...")
        devices = api.get_camera_devices()

        for device in devices:
            print("\n{}:".format(device['device_name']))
            print("  Type: {}".format(device['device_type']))
            print("  Room: {}".format(device.get('room_name', 'N/A')))
            print("  Doorbell: {}".format(device['is_doorbell']))
            print("  Motion detection: {}".format(device['has_motion']))
            print("  Person detection: {}".format(device['has_person']))

            # Get detailed status
            try:
                status = api.get_device_status(device['device_id'])
                print("  Connectivity: {}".format(status.get('connectivity_status', 'N/A')))
            except Exception as e:
                print("  Error getting status: {}".format(e))
    else:
        print("Usage: python google_nest_api.py <credentials_file.json>")
        print("\nCredentials file format:")
        print(json.dumps({
            'project_id': 'YOUR_DEVICE_ACCESS_PROJECT_ID',
            'client_id': 'YOUR_OAUTH_CLIENT_ID.apps.googleusercontent.com',
            'client_secret': 'YOUR_OAUTH_CLIENT_SECRET',
            'refresh_token': 'YOUR_REFRESH_TOKEN'
        }, indent=2))
