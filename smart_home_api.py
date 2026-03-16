# -*- coding: utf-8 -*-
"""
Smart Home REST API Server
Python 3.7+ compatible, uses only standard library.

Provides unified REST API for controlling smart home devices:
- SwitchBot devices
- Philips Hue lights
- Netatmo weather sensors
- Google Nest cameras
"""
import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class SmartHomeHandler(BaseHTTPRequestHandler):
    """HTTP request handler for smart home API."""

    # Class-level references (set by SmartHomeAPIServer)
    switchbot_api = None
    hue_api = None
    netatmo_api = None
    nest_api = None

    def log_message(self, format, *args):
        """Override to use logging module instead of stderr."""
        logging.debug("SmartHomeAPI: %s - %s", self.address_string(), format % args)

    def do_GET(self):
        """Handle GET requests."""
        segments = self._parse_path()

        # /api/health
        if segments[1:3] == ['api', 'health']:
            self._handle_health()
            return

        # /api/home/status
        if segments[1:4] == ['api', 'home', 'status']:
            self._handle_home_status()
            return

        # /api/switchbot/...
        if segments[1:3] == ['api', 'switchbot']:
            self._route_switchbot_get(segments)
            return

        # /api/hue/...
        if segments[1:3] == ['api', 'hue']:
            self._route_hue_get(segments)
            return

        # /api/netatmo/...
        if segments[1:4] == ['api', 'netatmo', 'environment']:
            self._handle_netatmo_environment()
            return

        # /api/nest/...
        if segments[1:3] == ['api', 'nest']:
            self._route_nest_get(segments)
            return

        self._send_error(404, "Not Found")

    def do_POST(self):
        """Handle POST requests."""
        segments = self._parse_path()

        # /api/switchbot/devices/{id}/command
        if (len(segments) == 6 and segments[1:4] == ['api', 'switchbot', 'devices']
                and segments[5] == 'command'):
            device_id = segments[4]
            self._handle_switchbot_device_command(device_id)
            return

        # /api/hue/setup/discover
        if segments[1:5] == ['api', 'hue', 'setup', 'discover']:
            self._handle_hue_discover()
            return

        # /api/hue/setup/register
        if segments[1:5] == ['api', 'hue', 'setup', 'register']:
            self._handle_hue_register()
            return

        self._send_error(404, "Not Found")

    def do_PUT(self):
        """Handle PUT requests."""
        segments = self._parse_path()

        # /api/hue/lights/{id}
        if (len(segments) == 5 and segments[1:4] == ['api', 'hue', 'lights']):
            light_id = segments[4]
            self._handle_hue_light_control(light_id)
            return

        # /api/hue/groups/{id}
        if (len(segments) == 5 and segments[1:4] == ['api', 'hue', 'groups']):
            group_id = segments[4]
            self._handle_hue_group_control(group_id)
            return

        # /api/hue/scenes/{id}
        if (len(segments) == 5 and segments[1:4] == ['api', 'hue', 'scenes']):
            scene_id = segments[4]
            self._handle_hue_scene_apply(scene_id)
            return

        self._send_error(404, "Not Found")

    # ========== Utility methods ==========

    def _send_json(self, data, status=200):
        """Send JSON response."""
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status, message):
        """Send error response."""
        self._send_json({"error": message}, status=status)

    def _read_body(self):
        """Read and parse JSON request body."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length)
        return json.loads(raw.decode('utf-8'))

    def _parse_path(self):
        """Parse URL path into segments."""
        # Strip query string if present
        path = self.path.split('?')[0]
        return path.split('/')

    # ========== GET routing helpers ==========

    def _route_switchbot_get(self, segments):
        """Route SwitchBot GET requests."""
        # /api/switchbot/devices
        if len(segments) == 4 and segments[3] == 'devices':
            self._handle_switchbot_devices()
            return

        # /api/switchbot/devices/{id}/status
        if (len(segments) == 6 and segments[3] == 'devices'
                and segments[5] == 'status'):
            device_id = segments[4]
            self._handle_switchbot_device_status(device_id)
            return

        self._send_error(404, "Not Found")

    def _route_hue_get(self, segments):
        """Route Hue GET requests."""
        if len(segments) < 4:
            self._send_error(404, "Not Found")
            return

        resource = segments[3]

        # /api/hue/lights
        if resource == 'lights' and len(segments) == 4:
            self._handle_hue_lights()
            return

        # /api/hue/groups
        if resource == 'groups' and len(segments) == 4:
            self._handle_hue_groups()
            return

        # /api/hue/scenes
        if resource == 'scenes' and len(segments) == 4:
            self._handle_hue_scenes()
            return

        self._send_error(404, "Not Found")

    def _route_nest_get(self, segments):
        """Route Nest GET requests."""
        if len(segments) < 4:
            self._send_error(404, "Not Found")
            return

        resource = segments[3]

        # /api/nest/cameras
        if resource == 'cameras' and len(segments) == 4:
            self._handle_nest_cameras()
            return

        # /api/nest/cameras/{id}
        if resource == 'cameras' and len(segments) == 5:
            camera_id = segments[4]
            self._handle_nest_camera(camera_id)
            return

        self._send_error(404, "Not Found")

    # ========== Health & Status handlers ==========

    def _handle_health(self):
        """Handle health check endpoint."""
        self._send_json({
            "status": "ok",
            "services": {
                "switchbot": self.switchbot_api is not None,
                "hue": self.hue_api is not None,
                "netatmo": self.netatmo_api is not None,
                "nest": self.nest_api is not None
            }
        })

    def _handle_home_status(self):
        """Handle unified home status endpoint."""
        result = {}

        # SwitchBot
        if self.switchbot_api is not None:
            try:
                devices = self.switchbot_api.get_all_device_statuses()
                result['switchbot'] = {"devices": devices}
            except Exception as e:
                logging.error("SmartHomeAPI: Failed to get SwitchBot status: %s", e)
                result['switchbot'] = {"error": str(e)}
        else:
            result['switchbot'] = {"error": "SwitchBot API is not configured"}

        # Hue
        if self.hue_api is not None:
            try:
                lights = self.hue_api.get_lights()
                groups = self.hue_api.get_groups()
                result['hue'] = {"lights": lights, "groups": groups}
            except Exception as e:
                logging.error("SmartHomeAPI: Failed to get Hue status: %s", e)
                result['hue'] = {"error": str(e)}
        else:
            result['hue'] = {"error": "Hue API is not configured"}

        # Netatmo
        if self.netatmo_api is not None:
            try:
                sensors = self.netatmo_api.get_all_sensor_readings()
                result['netatmo'] = {"sensors": sensors}
            except Exception as e:
                logging.error("SmartHomeAPI: Failed to get Netatmo status: %s", e)
                result['netatmo'] = {"error": str(e)}
        else:
            result['netatmo'] = {"error": "Netatmo API is not configured"}

        # Nest
        if self.nest_api is not None:
            try:
                cameras = self.nest_api.get_camera_devices()
                result['nest'] = {"cameras": cameras}
            except Exception as e:
                logging.error("SmartHomeAPI: Failed to get Nest status: %s", e)
                result['nest'] = {"error": str(e)}
        else:
            result['nest'] = {"error": "Nest API is not configured"}

        self._send_json(result)

    # ========== SwitchBot handlers ==========

    def _handle_switchbot_devices(self):
        """Handle GET /api/switchbot/devices."""
        if self.switchbot_api is None:
            self._send_error(503, "SwitchBot API is not configured")
            return

        try:
            devices = self.switchbot_api.get_devices()
            self._send_json(devices)
        except Exception as e:
            logging.error("SmartHomeAPI: Failed to get SwitchBot devices: %s", e)
            self._send_error(500, str(e))

    def _handle_switchbot_device_status(self, device_id):
        """Handle GET /api/switchbot/devices/{id}/status."""
        if self.switchbot_api is None:
            self._send_error(503, "SwitchBot API is not configured")
            return

        try:
            status = self.switchbot_api.get_device_status(device_id)
            self._send_json(status)
        except Exception as e:
            logging.error("SmartHomeAPI: Failed to get SwitchBot device status: %s", e)
            self._send_error(500, str(e))

    def _handle_switchbot_device_command(self, device_id):
        """Handle POST /api/switchbot/devices/{id}/command."""
        if self.switchbot_api is None:
            self._send_error(503, "SwitchBot API is not configured")
            return

        try:
            body = self._read_body()
            command_data = {
                "command": body.get("command", ""),
                "parameter": body.get("parameter", "default"),
                "commandType": body.get("commandType", "command")
            }
            result = self.switchbot_api._request(
                'POST',
                '/devices/{}/commands'.format(device_id),
                command_data
            )
            self._send_json(result)
        except Exception as e:
            logging.error("SmartHomeAPI: Failed to send SwitchBot command: %s", e)
            self._send_error(500, str(e))

    # ========== Hue handlers ==========

    def _handle_hue_lights(self):
        """Handle GET /api/hue/lights."""
        if self.hue_api is None:
            self._send_error(503, "Hue API is not configured")
            return

        try:
            lights = self.hue_api.get_lights()
            self._send_json(lights)
        except Exception as e:
            logging.error("SmartHomeAPI: Failed to get Hue lights: %s", e)
            self._send_error(500, str(e))

    def _handle_hue_light_control(self, light_id):
        """Handle PUT /api/hue/lights/{id}."""
        if self.hue_api is None:
            self._send_error(503, "Hue API is not configured")
            return

        try:
            body = self._read_body()
            result = self.hue_api.set_light_state(light_id, **body)
            self._send_json(result)
        except Exception as e:
            logging.error("SmartHomeAPI: Failed to control Hue light: %s", e)
            self._send_error(500, str(e))

    def _handle_hue_groups(self):
        """Handle GET /api/hue/groups."""
        if self.hue_api is None:
            self._send_error(503, "Hue API is not configured")
            return

        try:
            groups = self.hue_api.get_groups()
            self._send_json(groups)
        except Exception as e:
            logging.error("SmartHomeAPI: Failed to get Hue groups: %s", e)
            self._send_error(500, str(e))

    def _handle_hue_group_control(self, group_id):
        """Handle PUT /api/hue/groups/{id}."""
        if self.hue_api is None:
            self._send_error(503, "Hue API is not configured")
            return

        try:
            body = self._read_body()
            result = self.hue_api.set_group_action(group_id, **body)
            self._send_json(result)
        except Exception as e:
            logging.error("SmartHomeAPI: Failed to control Hue group: %s", e)
            self._send_error(500, str(e))

    def _handle_hue_scenes(self):
        """Handle GET /api/hue/scenes."""
        if self.hue_api is None:
            self._send_error(503, "Hue API is not configured")
            return

        try:
            scenes = self.hue_api.get_scenes()
            self._send_json(scenes)
        except Exception as e:
            logging.error("SmartHomeAPI: Failed to get Hue scenes: %s", e)
            self._send_error(500, str(e))

    def _handle_hue_scene_apply(self, scene_id):
        """Handle PUT /api/hue/scenes/{id}."""
        if self.hue_api is None:
            self._send_error(503, "Hue API is not configured")
            return

        try:
            body = self._read_body()
            group_id = body.get("group_id")
            if not group_id:
                self._send_error(400, "group_id is required")
                return
            result = self.hue_api.activate_scene(group_id, scene_id)
            self._send_json(result)
        except Exception as e:
            logging.error("SmartHomeAPI: Failed to apply Hue scene: %s", e)
            self._send_error(500, str(e))

    def _handle_hue_discover(self):
        """Handle POST /api/hue/setup/discover."""
        if self.hue_api is None:
            self._send_error(503, "Hue API is not configured")
            return

        try:
            bridges = self.hue_api.discover_bridge()
            self._send_json(bridges)
        except Exception as e:
            logging.error("SmartHomeAPI: Failed to discover Hue bridges: %s", e)
            self._send_error(500, str(e))

    def _handle_hue_register(self):
        """Handle POST /api/hue/setup/register."""
        if self.hue_api is None:
            self._send_error(503, "Hue API is not configured")
            return

        try:
            body = self._read_body()
            device_type = body.get('device_type', 'switchbot_hub#raspberry_pi') if body else 'switchbot_hub#raspberry_pi'
            result = self.hue_api.register(device_type=device_type)
            self._send_json(result)
        except Exception as e:
            logging.error("SmartHomeAPI: Failed to register with Hue bridge: %s", e)
            self._send_error(500, str(e))

    # ========== Netatmo handlers ==========

    def _handle_netatmo_environment(self):
        """Handle GET /api/netatmo/environment."""
        if self.netatmo_api is None:
            self._send_error(503, "Netatmo API is not configured")
            return

        try:
            sensors = self.netatmo_api.get_all_sensor_readings()
            self._send_json({"sensors": sensors})
        except Exception as e:
            logging.error("SmartHomeAPI: Failed to get Netatmo environment: %s", e)
            self._send_error(500, str(e))

    # ========== Nest handlers ==========

    def _handle_nest_cameras(self):
        """Handle GET /api/nest/cameras."""
        if self.nest_api is None:
            self._send_error(503, "Nest API is not configured")
            return

        try:
            cameras = self.nest_api.get_camera_devices()
            self._send_json({"cameras": cameras})
        except Exception as e:
            logging.error("SmartHomeAPI: Failed to get Nest cameras: %s", e)
            self._send_error(500, str(e))

    def _handle_nest_camera(self, camera_id):
        """Handle GET /api/nest/cameras/{id}."""
        if self.nest_api is None:
            self._send_error(503, "Nest API is not configured")
            return

        try:
            status = self.nest_api.get_device_status(camera_id)
            self._send_json(status)
        except Exception as e:
            logging.error("SmartHomeAPI: Failed to get Nest camera status: %s", e)
            self._send_error(500, str(e))


class SmartHomeAPIServer:
    """REST API server for smart home control."""

    def __init__(self, port=9000, switchbot_api=None, hue_api=None,
                 netatmo_api=None, nest_api=None):
        """
        Initialize Smart Home API server.

        Args:
            port: TCP port to listen on (default: 9000)
            switchbot_api: SwitchBotAPI instance or None
            hue_api: Hue API instance or None
            netatmo_api: NetatmoAPI instance or None
            nest_api: GoogleNestAPI instance or None
        """
        self.port = port
        self.switchbot_api = switchbot_api
        self.hue_api = hue_api
        self.netatmo_api = netatmo_api
        self.nest_api = nest_api
        self.server = None
        self.thread = None
        self._running = False

    def start(self):
        """Start the API server in a background thread."""
        SmartHomeHandler.switchbot_api = self.switchbot_api
        SmartHomeHandler.hue_api = self.hue_api
        SmartHomeHandler.netatmo_api = self.netatmo_api
        SmartHomeHandler.nest_api = self.nest_api

        self.server = HTTPServer(('0.0.0.0', self.port), SmartHomeHandler)
        self._running = True
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        logging.info("SmartHomeAPI server started on port %d", self.port)

    def _serve(self):
        """Serve requests until stopped."""
        while self._running:
            try:
                self.server.handle_request()
            except Exception as e:
                if self._running:
                    logging.error("SmartHomeAPI server error: %s", e)

    def stop(self):
        """Stop the API server."""
        self._running = False
        if self.server:
            self.server.server_close()
        logging.info("SmartHomeAPI server stopped")


if __name__ == '__main__':
    import os
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    # Load config
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    if not os.path.exists(config_path):
        print("config.json not found. Please create it from config.json.example")
        sys.exit(1)

    with open(config_path, 'r') as f:
        config = json.load(f)

    # Initialize APIs based on config
    switchbot_api = None
    netatmo_api = None
    nest_api = None

    # SwitchBot
    switchbot_config = config.get('switchbot', {})
    if switchbot_config.get('token') and switchbot_config.get('secret'):
        from switchbot_api import SwitchBotAPI
        switchbot_api = SwitchBotAPI(
            token=switchbot_config['token'],
            secret=switchbot_config['secret']
        )
        logging.info("SwitchBot API initialized")

    # Netatmo
    netatmo_config = config.get('netatmo', {})
    if netatmo_config.get('enabled', False):
        from netatmo_api import NetatmoAPI
        netatmo_api = NetatmoAPI(
            client_id=netatmo_config['client_id'],
            client_secret=netatmo_config['client_secret'],
            refresh_token=netatmo_config['refresh_token'],
            credentials_file=netatmo_config.get('credentials_file')
        )
        logging.info("Netatmo API initialized")

    # Google Nest
    nest_config = config.get('google_nest', {})
    if nest_config.get('enabled', False):
        from google_nest_api import GoogleNestAPI
        nest_api = GoogleNestAPI(
            project_id=nest_config['project_id'],
            client_id=nest_config['client_id'],
            client_secret=nest_config['client_secret'],
            refresh_token=nest_config['refresh_token'],
            credentials_file=nest_config.get('credentials_file')
        )
        logging.info("Google Nest API initialized")

    # Start server
    api_config = config.get('smart_home_api', {})
    port = api_config.get('port', 9000)

    server = SmartHomeAPIServer(
        port=port,
        switchbot_api=switchbot_api,
        hue_api=None,  # Hue API not yet implemented in project
        netatmo_api=netatmo_api,
        nest_api=nest_api
    )
    server.start()

    print("Smart Home API server running on port {}".format(port))
    print("Press Ctrl+C to stop")

    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.stop()
