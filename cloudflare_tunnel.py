# -*- coding: utf-8 -*-
"""
Cloudflare Tunnel manager for exposing local webhook server.
Python 3.7+ compatible, uses only standard library.
"""
import logging
import subprocess
import threading
import time
import shutil


class CloudflareTunnel:
    """Manages cloudflared tunnel process."""

    def __init__(self, local_port, hostname=None, config_path=None):
        """
        Initialize Cloudflare Tunnel manager.

        Args:
            local_port: Local port to tunnel (e.g., 8080)
            hostname: Optional hostname for named tunnel (e.g., webhook.example.com)
            config_path: Optional path to cloudflared config file
        """
        self.local_port = local_port
        self.hostname = hostname
        self.config_path = config_path
        self.process = None
        self.thread = None
        self.public_url = None
        self._stop_event = threading.Event()

    def _check_cloudflared(self):
        """Check if cloudflared is installed."""
        return shutil.which('cloudflared') is not None

    def _build_command(self):
        """Build cloudflared command."""
        if self.config_path:
            # Use config file (for named tunnels with pre-configured routes)
            return ['cloudflared', 'tunnel', '--config', self.config_path, 'run']
        elif self.hostname:
            # Named tunnel with hostname
            return [
                'cloudflared', 'tunnel',
                '--url', 'http://localhost:{}'.format(self.local_port),
                '--hostname', self.hostname
            ]
        else:
            # Quick tunnel (generates random URL)
            return [
                'cloudflared', 'tunnel',
                '--url', 'http://localhost:{}'.format(self.local_port)
            ]

    def start(self):
        """Start cloudflared tunnel."""
        if not self._check_cloudflared():
            logging.error("cloudflared not found. Please install it first.")
            logging.error("See: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/")
            return False

        cmd = self._build_command()
        logging.info("Starting cloudflared: %s", ' '.join(cmd))

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
        except Exception as e:
            logging.error("Failed to start cloudflared: %s", e)
            return False

        # Start output monitoring thread
        self._stop_event.clear()
        self.thread = threading.Thread(target=self._monitor_output, daemon=True)
        self.thread.start()

        # Wait a bit for tunnel to establish
        time.sleep(3)

        if self.process.poll() is not None:
            logging.error("cloudflared exited immediately with code %d", self.process.returncode)
            return False

        logging.info("Cloudflare tunnel started")
        if self.hostname:
            self.public_url = "https://{}".format(self.hostname)
            logging.info("Tunnel URL: %s", self.public_url)

        return True

    def _monitor_output(self):
        """Monitor cloudflared output for URL and errors."""
        try:
            for line in self.process.stdout:
                if self._stop_event.is_set():
                    break

                line = line.strip()
                if not line:
                    continue

                # Log output
                logging.debug("[cloudflared] %s", line)

                # Try to extract URL from quick tunnel
                if 'trycloudflare.com' in line or '.cloudflare' in line:
                    # Extract URL from output
                    import re
                    match = re.search(r'https://[^\s]+\.trycloudflare\.com', line)
                    if match:
                        self.public_url = match.group(0)
                        logging.info("Quick tunnel URL: %s", self.public_url)

                # Check for errors
                if 'error' in line.lower() or 'failed' in line.lower():
                    logging.warning("[cloudflared] %s", line)

        except Exception as e:
            if not self._stop_event.is_set():
                logging.error("Error monitoring cloudflared: %s", e)

    def stop(self):
        """Stop cloudflared tunnel."""
        self._stop_event.set()

        if self.process:
            logging.info("Stopping cloudflared tunnel...")
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                logging.warning("cloudflared did not terminate, killing...")
                self.process.kill()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass  # Give up, process will be orphaned
            except Exception as e:
                logging.error("Error stopping cloudflared: %s", e)
            finally:
                self.process = None

        self.public_url = None
        logging.info("Cloudflare tunnel stopped")

    def is_running(self):
        """Check if tunnel is running."""
        return self.process is not None and self.process.poll() is None

    def get_webhook_url(self, path):
        """
        Get full webhook URL.

        Args:
            path: Webhook path (e.g., '/switchbot/webhook')

        Returns:
            str: Full webhook URL or None if tunnel not running
        """
        if self.public_url:
            return "{}{}".format(self.public_url.rstrip('/'), path)
        return None


if __name__ == '__main__':
    # Test tunnel
    logging.basicConfig(level=logging.DEBUG)

    tunnel = CloudflareTunnel(local_port=8080)

    print("Starting tunnel (quick mode)...")
    if tunnel.start():
        print("Tunnel running!")
        print("Public URL: {}".format(tunnel.public_url))
        print("Webhook URL: {}".format(tunnel.get_webhook_url('/switchbot/webhook')))
        print("Press Ctrl+C to stop...")

        try:
            while tunnel.is_running():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            tunnel.stop()
    else:
        print("Failed to start tunnel")
