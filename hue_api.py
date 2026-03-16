# -*- coding: utf-8 -*-
"""
Hue Bridge v1 REST API (HTTP)
Python 3.7+ compatible, requires only requests library.

Local network HTTP client for Philips Hue Bridge.
Reference: https://developers.meethue.com/develop/hue-api/
"""
import json
import logging
import os

import requests


class HueAPI:
    """Philips Hue Bridge API client (v1 REST API over HTTP)."""

    DISCOVERY_URL = "https://discovery.meethue.com"

    def __init__(self, bridge_ip=None, api_key=None):
        """
        Initialize Hue API client.

        Args:
            bridge_ip: IP address of the Hue Bridge on local network
            api_key: API key (username) for authenticated requests
        """
        self.bridge_ip = bridge_ip
        self.api_key = api_key

    @property
    def base_url(self):
        """Base URL for authenticated API requests."""
        return "http://{}/api/{}".format(self.bridge_ip, self.api_key)

    def _request(self, method, path, data=None):
        """
        Make HTTP request to Hue Bridge. Returns parsed JSON.

        Args:
            method: HTTP method (GET, PUT, POST, DELETE)
            path: URL path (full URL)
            data: Request body dict for POST/PUT requests

        Returns:
            Parsed JSON response (dict or list)

        Raises:
            requests.exceptions.RequestException: On network errors
            ValueError: On Hue API error response
        """
        if method.upper() == 'GET':
            response = requests.get(path, timeout=(3, 10))
        elif method.upper() == 'PUT':
            response = requests.put(path, json=data, timeout=(3, 10))
        elif method.upper() == 'POST':
            response = requests.post(path, json=data, timeout=(3, 10))
        elif method.upper() == 'DELETE':
            response = requests.delete(path, timeout=(3, 10))
        else:
            raise ValueError("Unsupported HTTP method: {}".format(method))

        response.raise_for_status()
        result = response.json()

        # Hue API returns errors as a list: [{"error": {"type": N, "description": "..."}}]
        if isinstance(result, list) and len(result) > 0:
            first = result[0]
            if isinstance(first, dict) and 'error' in first:
                error = first['error']
                raise ValueError("Hue API error (type {}): {}".format(
                    error.get('type', 'unknown'),
                    error.get('description', 'Unknown error')
                ))

        return result

    # ===== Setup =====

    def discover_bridge(self):
        """
        Discover Hue Bridge IP via N-UPnP.

        Returns:
            list: List of dicts with bridge info [{id, internalipaddress}, ...]
        """
        response = requests.get(self.DISCOVERY_URL, timeout=(5, 10))
        response.raise_for_status()
        bridges = response.json()
        logging.info("Discovered %d Hue Bridge(s)", len(bridges))
        return bridges

    def register(self, device_type='switchbot_hub#raspberry_pi'):
        """
        Register with bridge (link button must be pressed first).

        The Hue Bridge link button must be pressed within 30 seconds
        before calling this method.

        Args:
            device_type: Application identifier string

        Returns:
            str: API key (username) for authenticated requests

        Raises:
            ValueError: If link button was not pressed or other error
        """
        url = "http://{}/api".format(self.bridge_ip)
        data = {"devicetype": device_type}

        result = self._request('POST', url, data)

        # Success response: [{"success": {"username": "THE_API_KEY"}}]
        if isinstance(result, list) and len(result) > 0:
            first = result[0]
            if isinstance(first, dict) and 'success' in first:
                api_key = first['success']['username']
                self.api_key = api_key
                logging.info("Registered with Hue Bridge, API key obtained")
                return api_key

        raise ValueError("Unexpected registration response: {}".format(result))

    # ===== Lights =====

    def get_lights(self):
        """
        Get all lights.

        Returns:
            dict: {id: {name, state, type, ...}}
        """
        url = "{}/lights".format(self.base_url)
        return self._request('GET', url)

    def get_light(self, light_id):
        """
        Get single light status.

        Args:
            light_id: Light ID (string or int)

        Returns:
            dict: Light info with state, name, type, etc.
        """
        url = "{}/lights/{}".format(self.base_url, light_id)
        return self._request('GET', url)

    def set_light_state(self, light_id, on=None, bri=None, hue=None, sat=None, ct=None):
        """
        Set light state. Only non-None params are sent.

        Args:
            light_id: Light ID (string or int)
            on: Power state (bool)
            bri: Brightness (0-254)
            hue: Hue (0-65535)
            sat: Saturation (0-254)
            ct: Color temperature in mirek (153-500)

        Returns:
            list: Success/error responses from bridge
        """
        state = {}
        if on is not None:
            state['on'] = on
        if bri is not None:
            state['bri'] = bri
        if hue is not None:
            state['hue'] = hue
        if sat is not None:
            state['sat'] = sat
        if ct is not None:
            state['ct'] = ct

        url = "{}/lights/{}/state".format(self.base_url, light_id)
        return self._request('PUT', url, state)

    # ===== Groups =====

    def get_groups(self):
        """
        Get all groups (rooms).

        Returns:
            dict: {id: {name, lights, type, action, ...}}
        """
        url = "{}/groups".format(self.base_url)
        return self._request('GET', url)

    def get_group(self, group_id):
        """
        Get single group.

        Args:
            group_id: Group ID (string or int)

        Returns:
            dict: Group info with name, lights, action, etc.
        """
        url = "{}/groups/{}".format(self.base_url, group_id)
        return self._request('GET', url)

    def set_group_action(self, group_id, on=None, bri=None, hue=None, sat=None, ct=None, scene=None):
        """
        Set group action. If scene is specified, activates that scene.

        Args:
            group_id: Group ID (string or int)
            on: Power state (bool)
            bri: Brightness (0-254)
            hue: Hue (0-65535)
            sat: Saturation (0-254)
            ct: Color temperature in mirek (153-500)
            scene: Scene ID to activate

        Returns:
            list: Success/error responses from bridge
        """
        action = {}
        if on is not None:
            action['on'] = on
        if bri is not None:
            action['bri'] = bri
        if hue is not None:
            action['hue'] = hue
        if sat is not None:
            action['sat'] = sat
        if ct is not None:
            action['ct'] = ct
        if scene is not None:
            action['scene'] = scene

        url = "{}/groups/{}/action".format(self.base_url, group_id)
        return self._request('PUT', url, action)

    # ===== Scenes =====

    def get_scenes(self):
        """
        Get all scenes.

        Returns:
            dict: {id: {name, group, lights, ...}}
        """
        url = "{}/scenes".format(self.base_url)
        return self._request('GET', url)

    def activate_scene(self, group_id, scene_id):
        """
        Activate a scene in a specific group.

        Args:
            group_id: Group ID to apply the scene to
            scene_id: Scene ID to activate

        Returns:
            list: Success/error responses from bridge
        """
        url = "{}/groups/{}/action".format(self.base_url, group_id)
        return self._request('PUT', url, {"scene": scene_id})


if __name__ == '__main__':
    # Simple test - requires config.json with hue settings
    logging.basicConfig(level=logging.DEBUG)

    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = json.load(f)

        hue_config = config.get('hue', {})
        bridge_ip = hue_config.get('bridge_ip')
        api_key = hue_config.get('api_key')

        if not bridge_ip:
            print("No bridge_ip in config. Attempting discovery...")
            api = HueAPI()
            bridges = api.discover_bridge()
            print("Found bridges:")
            print(json.dumps(bridges, indent=2))
            if bridges:
                bridge_ip = bridges[0].get('internalipaddress')
                print("Using bridge IP: {}".format(bridge_ip))

        if bridge_ip:
            api = HueAPI(bridge_ip=bridge_ip, api_key=api_key)

            if not api_key:
                print("No api_key in config. Press the bridge link button, then press Enter...")
                input()
                try:
                    api_key = api.register()
                    print("Registered! API key: {}".format(api_key))
                except ValueError as e:
                    print("Registration failed: {}".format(e))
                    exit(1)

            print("\nFetching lights...")
            lights = api.get_lights()
            print(json.dumps(lights, indent=2, ensure_ascii=False))

            print("\nFetching groups...")
            groups = api.get_groups()
            print(json.dumps(groups, indent=2, ensure_ascii=False))

            print("\nFetching scenes...")
            scenes = api.get_scenes()
            print(json.dumps(scenes, indent=2, ensure_ascii=False))
    else:
        print("config.json not found. Please create it from config.json.example")
