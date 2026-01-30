# -*- coding: utf-8 -*-
"""
Webhook HTTP server for receiving SwitchBot events.
Python 3.7+ compatible, uses only standard library.
"""
import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP request handler for SwitchBot webhooks."""

    # Class-level callback and path (set by WebhookServer)
    callback = None
    webhook_path = '/switchbot/webhook'

    def log_message(self, format, *args):
        """Override to use logging module."""
        logging.debug("Webhook HTTP: %s", format % args)

    def _send_response(self, status_code, body=None):
        """Send HTTP response."""
        try:
            self.send_response(status_code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            if body:
                self.wfile.write(json.dumps(body).encode('utf-8'))
        except BrokenPipeError:
            # Client closed connection before response - this is OK for webhooks
            pass
        except Exception as e:
            logging.debug("Error sending response: %s", e)

    def do_GET(self):
        """Handle GET requests (health check)."""
        if self.path == '/health':
            self._send_response(200, {'status': 'ok'})
        else:
            self._send_response(404, {'error': 'Not found'})

    def do_POST(self):
        """Handle POST requests (webhook events)."""
        # Check path
        if self.path != self.webhook_path:
            self._send_response(404, {'error': 'Not found'})
            return

        # Read body
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            self._send_response(400, {'error': 'Empty body'})
            return

        try:
            body = self.rfile.read(content_length)
            event_data = json.loads(body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logging.error("Failed to parse webhook body: %s", e)
            self._send_response(400, {'error': 'Invalid JSON'})
            return

        logging.debug("Received webhook event: %s", event_data)

        # Process event via callback
        if self.callback:
            try:
                self.callback(event_data)
            except Exception as e:
                logging.error("Webhook callback error: %s", e)

        # Always respond 200 to SwitchBot
        self._send_response(200, {'status': 'received'})


class WebhookServer:
    """Threaded HTTP server for webhooks."""

    def __init__(self, port=8080, path='/switchbot/webhook', callback=None):
        """
        Initialize webhook server.

        Args:
            port: Port to listen on
            path: URL path for webhook endpoint
            callback: Function to call with event data
        """
        self.port = port
        self.path = path
        self.callback = callback
        self.server = None
        self.thread = None

    def start(self):
        """Start the webhook server in a background thread."""
        # Configure handler
        WebhookHandler.callback = self.callback
        WebhookHandler.webhook_path = self.path

        # Create server
        self.server = HTTPServer(('0.0.0.0', self.port), WebhookHandler)
        self.server.socket.settimeout(1)  # Allow periodic checks for shutdown

        # Start in background thread
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

        logging.info("Webhook server started on port %d, path: %s", self.port, self.path)

    def _serve(self):
        """Server loop with graceful shutdown support."""
        while True:
            try:
                self.server.handle_request()
            except Exception as e:
                if self.server is None:
                    break  # Server was stopped
                logging.debug("Server handle_request: %s", e)

    def stop(self):
        """Stop the webhook server."""
        if self.server:
            logging.info("Stopping webhook server...")
            server = self.server
            self.server = None
            # Don't call shutdown() - we use custom loop with handle_request()
            # Just close the socket; the daemon thread will exit on its own
            try:
                server.server_close()
            except Exception:
                pass

    def get_local_url(self):
        """Get local webhook URL."""
        return "http://localhost:{port}{path}".format(port=self.port, path=self.path)


def parse_webhook_event(event_data):
    """
    Parse SwitchBot webhook event into structured data.

    Args:
        event_data: Raw event data from webhook

    Returns:
        dict: Parsed event with device_id, device_type, status, etc.
    """
    event_type = event_data.get('eventType')
    event_version = event_data.get('eventVersion')
    context = event_data.get('context', {})

    device_type = context.get('deviceType', 'Unknown')
    device_mac = context.get('deviceMac', '')

    # Extract status fields (varies by device type)
    status = {}
    ignore_keys = {'deviceType', 'deviceMac', 'timeOfSample'}

    for key, value in context.items():
        if key not in ignore_keys:
            status[key] = value

    return {
        'event_type': event_type,
        'event_version': event_version,
        'device_type': device_type,
        'device_mac': device_mac,
        'device_id': device_mac,  # MAC is used as device ID in webhooks
        'status': status,
        'timestamp': context.get('timeOfSample'),
        'raw': event_data
    }


if __name__ == '__main__':
    # Test server
    logging.basicConfig(level=logging.DEBUG)

    def test_callback(event):
        print("Received event: {}".format(json.dumps(event, indent=2, ensure_ascii=False)))

    server = WebhookServer(port=8080, callback=test_callback)
    server.start()

    print("Test server running on {}".format(server.get_local_url()))
    print("Press Ctrl+C to stop...")

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        print("Server stopped")
