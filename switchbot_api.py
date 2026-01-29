# -*- coding: utf-8 -*-
"""
SwitchBot API v1.1 Client
Python 3.7+ compatible, requires only requests library
"""
import time
import hashlib
import hmac
import base64
import uuid
import json
import requests


class SwitchBotAPI:
    """SwitchBot API v1.1 client with HMAC-SHA256 authentication."""

    BASE_URL = "https://api.switch-bot.com/v1.1"

    def __init__(self, token, secret):
        """
        Initialize SwitchBot API client.

        Args:
            token: API token from SwitchBot app
            secret: API secret key from SwitchBot app
        """
        self.token = token
        self.secret = secret

    def _generate_headers(self):
        """Generate authentication headers for API request."""
        t = int(round(time.time() * 1000))
        nonce = str(uuid.uuid4())
        string_to_sign = "{}{}{}".format(self.token, t, nonce)

        sign = base64.b64encode(
            hmac.new(
                self.secret.encode('utf-8'),
                string_to_sign.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')

        return {
            'Authorization': self.token,
            't': str(t),
            'sign': sign,
            'nonce': nonce,
            'Content-Type': 'application/json; charset=utf8'
        }

    def _request(self, method, endpoint, data=None):
        """
        Make authenticated request to SwitchBot API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., '/devices')
            data: Request body for POST requests

        Returns:
            dict: API response body

        Raises:
            requests.exceptions.RequestException: On network errors
            ValueError: On API error response
        """
        url = "{}{}".format(self.BASE_URL, endpoint)
        headers = self._generate_headers()

        if method.upper() == 'GET':
            response = requests.get(url, headers=headers, timeout=30)
        elif method.upper() == 'POST':
            response = requests.post(url, headers=headers, json=data, timeout=30)
        else:
            raise ValueError("Unsupported HTTP method: {}".format(method))

        response.raise_for_status()
        result = response.json()

        if result.get('statusCode') != 100:
            raise ValueError("API error: {} - {}".format(
                result.get('statusCode'),
                result.get('message', 'Unknown error')
            ))

        return result.get('body', {})

    def get_devices(self):
        """
        Get list of all SwitchBot devices.

        Returns:
            dict: Contains 'deviceList' and 'infraredRemoteList'
        """
        return self._request('GET', '/devices')

    def get_device_status(self, device_id):
        """
        Get status of a specific device.

        Args:
            device_id: Device ID to query

        Returns:
            dict: Device status data
        """
        endpoint = '/devices/{}/status'.format(device_id)
        return self._request('GET', endpoint)

    def get_all_device_statuses(self):
        """
        Get statuses of all physical devices.

        Returns:
            list: List of dicts with device info and status
        """
        devices_data = self.get_devices()
        device_list = devices_data.get('deviceList', [])

        results = []
        for device in device_list:
            device_id = device.get('deviceId')
            device_name = device.get('deviceName', 'Unknown')
            device_type = device.get('deviceType', 'Unknown')

            try:
                status = self.get_device_status(device_id)
                results.append({
                    'device_id': device_id,
                    'device_name': device_name,
                    'device_type': device_type,
                    'status': status,
                    'error': None
                })
            except Exception as e:
                results.append({
                    'device_id': device_id,
                    'device_name': device_name,
                    'device_type': device_type,
                    'status': None,
                    'error': str(e)
                })

        return results

    # ========== Webhook Management ==========

    def setup_webhook(self, url):
        """
        Setup webhook URL for receiving device events.

        Args:
            url: Webhook URL to receive events

        Returns:
            dict: API response
        """
        data = {
            'action': 'setupWebhook',
            'url': url,
            'deviceList': 'ALL'
        }
        return self._request('POST', '/webhook/setupWebhook', data)

    def query_webhook(self):
        """
        Query current webhook configuration.

        Returns:
            dict: Current webhook settings (urls list)
        """
        data = {
            'action': 'queryUrl'
        }
        return self._request('POST', '/webhook/queryWebhook', data)

    def query_webhook_details(self, url):
        """
        Query webhook details for a specific URL.

        Args:
            url: Webhook URL to query

        Returns:
            dict: Webhook details (deviceList, createTime, lastUpdateTime)
        """
        data = {
            'action': 'queryDetails',
            'urls': [url]
        }
        return self._request('POST', '/webhook/queryWebhook', data)

    def update_webhook(self, url, enable=True):
        """
        Update webhook configuration.

        Args:
            url: Webhook URL
            enable: Enable or disable the webhook

        Returns:
            dict: API response
        """
        data = {
            'action': 'updateWebhook',
            'config': {
                'url': url,
                'enable': enable
            }
        }
        return self._request('POST', '/webhook/updateWebhook', data)

    def delete_webhook(self, url):
        """
        Delete webhook configuration.

        Args:
            url: Webhook URL to delete

        Returns:
            dict: API response
        """
        data = {
            'action': 'deleteWebhook',
            'url': url
        }
        return self._request('POST', '/webhook/deleteWebhook', data)


if __name__ == '__main__':
    # Simple test - requires config.json
    import os
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = json.load(f)

        api = SwitchBotAPI(config['switchbot']['token'], config['switchbot']['secret'])

        print("Fetching devices...")
        devices = api.get_devices()
        print(json.dumps(devices, indent=2, ensure_ascii=False))
    else:
        print("config.json not found. Please create it from config.json.example")
