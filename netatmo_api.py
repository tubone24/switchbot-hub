# -*- coding: utf-8 -*-
"""
Netatmo Weather Station API client.
Python 3.7+ compatible, requires only requests library.

OAuth2 authentication with refresh token flow.
Reference: https://dev.netatmo.com/apidocumentation/oauth
"""
import json
import os
import time
import logging

import requests


class NetatmoAPI:
    """Netatmo Weather Station API client with OAuth2 authentication."""

    AUTH_URL = "https://api.netatmo.com/oauth2/token"
    API_BASE = "https://api.netatmo.com/api"

    # Module types
    MODULE_TYPES = {
        'NAMain': 'Indoor Station',      # Base station (indoor): temp, humidity, CO2, noise, pressure
        'NAModule1': 'Outdoor Module',   # Outdoor: temp, humidity
        'NAModule2': 'Wind Gauge',       # Wind: WindStrength, WindAngle, GustStrength, GustAngle
        'NAModule3': 'Rain Gauge',       # Rain: Rain, sum_rain_1, sum_rain_24
        'NAModule4': 'Indoor Module',    # Additional indoor: temp, humidity, CO2
    }

    # Outdoor module types (for is_outdoor flag)
    OUTDOOR_MODULE_TYPES = ['NAModule1', 'NAModule2', 'NAModule3']

    def __init__(self, client_id, client_secret, refresh_token, credentials_file=None):
        """
        Initialize Netatmo API client.

        Args:
            client_id: Netatmo app client ID
            client_secret: Netatmo app client secret
            refresh_token: OAuth2 refresh token
            credentials_file: Optional file path to persist updated refresh token
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.credentials_file = credentials_file

        self.access_token = None
        self.token_expires_at = 0

    def _refresh_access_token(self):
        """
        Refresh the access token using the refresh token.
        Updates self.access_token and self.token_expires_at.
        Optionally persists new refresh_token to credentials file.
        """
        payload = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'
        }

        try:
            response = requests.post(
                self.AUTH_URL,
                data=payload,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            self.access_token = data['access_token']
            expires_in = data.get('expires_in', 10800)  # Default 3 hours
            self.token_expires_at = time.time() + expires_in - 300  # 5 min buffer

            # Update refresh token if a new one is provided
            if 'refresh_token' in data and data['refresh_token'] != self.refresh_token:
                self.refresh_token = data['refresh_token']
                logging.info("Netatmo refresh token updated")

                # Persist to file if configured
                if self.credentials_file:
                    self._save_credentials()

            logging.debug("Netatmo access token refreshed, expires in %d seconds", expires_in)
            return True

        except requests.exceptions.RequestException as e:
            logging.error("Failed to refresh Netatmo access token: %s", e)
            if hasattr(e, 'response') and e.response is not None:
                logging.error("Response: %s", e.response.text)
            raise

    def _save_credentials(self):
        """Save updated credentials to file."""
        if not self.credentials_file:
            return

        try:
            credentials = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'refresh_token': self.refresh_token
            }
            with open(self.credentials_file, 'w') as f:
                json.dump(credentials, f, indent=2)
            logging.debug("Netatmo credentials saved to %s", self.credentials_file)
        except Exception as e:
            logging.warning("Failed to save Netatmo credentials: %s", e)

    def _ensure_valid_token(self):
        """Ensure we have a valid access token, refreshing if needed."""
        if not self.access_token or time.time() >= self.token_expires_at:
            self._refresh_access_token()

    def _api_request(self, endpoint, params=None):
        """
        Make an authenticated API request.

        Args:
            endpoint: API endpoint path (e.g., '/getstationsdata')
            params: Optional query parameters

        Returns:
            dict: Response body
        """
        self._ensure_valid_token()

        url = self.API_BASE + endpoint
        headers = {
            'Accept': 'application/json',
            'Authorization': 'Bearer {}'.format(self.access_token)
        }

        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logging.error("Netatmo API request failed: %s", e)
            if hasattr(e, 'response') and e.response is not None:
                logging.error("Response: %s", e.response.text)
            raise

    def get_stations_data(self, device_id=None):
        """
        Get weather station data.

        Args:
            device_id: Optional specific device MAC address

        Returns:
            dict: Station data with devices and modules
        """
        params = {}
        if device_id:
            params['device_id'] = device_id

        response = self._api_request('/getstationsdata', params)
        return response.get('body', {})

    def get_all_sensor_readings(self):
        """
        Get all sensor readings from all stations and modules.

        Returns:
            list: List of sensor readings with standardized format:
                  [{
                      'device_id': str,
                      'device_name': str,
                      'module_type': str,
                      'is_outdoor': bool,
                      'temperature': float or None,
                      'humidity': int or None,
                      'co2': int or None,
                      'pressure': float or None,
                      'noise': int or None,
                      'wind_strength': int or None,      # km/h
                      'wind_angle': int or None,         # degrees
                      'gust_strength': int or None,      # km/h
                      'gust_angle': int or None,         # degrees
                      'rain': float or None,             # mm (current)
                      'rain_1h': float or None,          # mm (last hour)
                      'rain_24h': float or None,         # mm (last 24 hours)
                      'battery_percent': int or None,
                      'wifi_status': int or None,
                      'rf_status': int or None,
                      'time_utc': int (unix timestamp)
                  }]
        """
        data = self.get_stations_data()
        devices = data.get('devices', [])
        readings = []

        for device in devices:
            # Main station (indoor)
            station_name = device.get('station_name', device.get('home_name', 'Unknown'))
            module_name = device.get('module_name', station_name)

            # Get dashboard data (current readings)
            dashboard = device.get('dashboard_data', {})

            if dashboard:
                reading = {
                    'device_id': device.get('_id'),
                    'device_name': module_name,
                    'station_name': station_name,
                    'module_type': device.get('type', 'NAMain'),
                    'is_outdoor': False,  # Main station is always indoor
                    'temperature': dashboard.get('Temperature'),
                    'humidity': dashboard.get('Humidity'),
                    'co2': dashboard.get('CO2'),
                    'pressure': dashboard.get('Pressure'),
                    'noise': dashboard.get('Noise'),
                    'wind_strength': None,
                    'wind_angle': None,
                    'gust_strength': None,
                    'gust_angle': None,
                    'rain': None,
                    'rain_1h': None,
                    'rain_24h': None,
                    'battery_percent': None,  # Main station has no battery
                    'wifi_status': device.get('wifi_status'),
                    'rf_status': None,
                    'time_utc': dashboard.get('time_utc')
                }
                readings.append(reading)

            # Process modules (outdoor, additional indoor, rain, wind)
            modules = device.get('modules', [])
            for module in modules:
                module_dashboard = module.get('dashboard_data', {})
                if not module_dashboard:
                    continue

                module_type = module.get('type', '')
                is_outdoor = module_type in self.OUTDOOR_MODULE_TYPES

                reading = {
                    'device_id': module.get('_id'),
                    'device_name': module.get('module_name', 'Module'),
                    'station_name': station_name,
                    'module_type': module_type,
                    'is_outdoor': is_outdoor,
                    'temperature': module_dashboard.get('Temperature'),
                    'humidity': module_dashboard.get('Humidity'),
                    'co2': module_dashboard.get('CO2'),
                    'pressure': None,  # Only main station has pressure
                    'noise': None,     # Only main station has noise
                    # Wind data (NAModule2)
                    'wind_strength': module_dashboard.get('WindStrength'),
                    'wind_angle': module_dashboard.get('WindAngle'),
                    'gust_strength': module_dashboard.get('GustStrength'),
                    'gust_angle': module_dashboard.get('GustAngle'),
                    # Rain data (NAModule3)
                    'rain': module_dashboard.get('Rain'),
                    'rain_1h': module_dashboard.get('sum_rain_1'),
                    'rain_24h': module_dashboard.get('sum_rain_24'),
                    'battery_percent': module.get('battery_percent'),
                    'wifi_status': None,
                    'rf_status': module.get('rf_status'),
                    'time_utc': module_dashboard.get('time_utc')
                }
                readings.append(reading)

        return readings

    def get_measure(self, device_id, module_id=None, scale='30min', data_type='Temperature,Humidity',
                    date_begin=None, date_end=None, limit=None, optimize=False, real_time=False):
        """
        Get historical measurements for a device/module.

        Args:
            device_id: Main station MAC address
            module_id: Optional module MAC address (if not specified, gets main station data)
            scale: Time interval ('30min', '1hour', '3hours', '1day', '1week', '1month')
            data_type: Comma-separated list of data types
                       (Temperature, Humidity, CO2, Pressure, Noise, Rain, WindStrength, WindAngle, etc.)
            date_begin: Optional start timestamp (Unix epoch)
            date_end: Optional end timestamp (Unix epoch)
            limit: Maximum number of measurements to return
            optimize: If True, timestamps are not returned (use scale interval)
            real_time: If True, get last data pushed by the station

        Returns:
            dict: Measurement data
        """
        params = {
            'device_id': device_id,
            'scale': scale,
            'type': data_type,
            'optimize': 'true' if optimize else 'false',
            'real_time': 'true' if real_time else 'false'
        }

        if module_id:
            params['module_id'] = module_id
        if date_begin:
            params['date_begin'] = date_begin
        if date_end:
            params['date_end'] = date_end
        if limit:
            params['limit'] = limit

        response = self._api_request('/getmeasure', params)
        return response.get('body', {})


def load_credentials_from_file(filepath):
    """
    Load Netatmo credentials from a JSON file.

    Args:
        filepath: Path to credentials JSON file

    Returns:
        dict: Credentials with client_id, client_secret, refresh_token
    """
    with open(filepath, 'r') as f:
        return json.load(f)


if __name__ == '__main__':
    # Simple test (requires valid credentials)
    import sys

    logging.basicConfig(level=logging.DEBUG)

    if len(sys.argv) > 1:
        creds = load_credentials_from_file(sys.argv[1])
        api = NetatmoAPI(
            client_id=creds['client_id'],
            client_secret=creds['client_secret'],
            refresh_token=creds['refresh_token']
        )

        print("Fetching station data...")
        readings = api.get_all_sensor_readings()

        for reading in readings:
            print("\n{}:".format(reading['device_name']))
            print("  Type: {} ({})".format(
                reading['module_type'],
                'Outdoor' if reading['is_outdoor'] else 'Indoor'
            ))
            if reading['temperature'] is not None:
                print("  Temperature: {}°C".format(reading['temperature']))
            if reading['humidity'] is not None:
                print("  Humidity: {}%".format(reading['humidity']))
            if reading['co2'] is not None:
                print("  CO2: {} ppm".format(reading['co2']))
            if reading['pressure'] is not None:
                print("  Pressure: {} mbar".format(reading['pressure']))
            if reading['noise'] is not None:
                print("  Noise: {} dB".format(reading['noise']))
    else:
        print("Usage: python netatmo_api.py <credentials_file.json>")
        print("\nCredentials file format:")
        print(json.dumps({
            'client_id': 'YOUR_CLIENT_ID',
            'client_secret': 'YOUR_CLIENT_SECRET',
            'refresh_token': 'YOUR_REFRESH_TOKEN'
        }, indent=2))
