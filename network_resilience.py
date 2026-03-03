# -*- coding: utf-8 -*-
"""
Network resilience utilities.
Provides network health checking, circuit breaker pattern, and retry with backoff.
"""
import enum
import logging
import socket
import threading
import time
import functools


class NetworkHealthChecker:
    """
    Check network connectivity with caching.
    Uses TCP connection to DNS server (8.8.8.8:53) as health probe.
    """

    def __init__(self, check_host='8.8.8.8', check_port=53, check_timeout=3, cache_ttl=30):
        """
        Args:
            check_host: Host to check connectivity against
            check_port: Port to check
            check_timeout: Timeout for connectivity check in seconds
            cache_ttl: How long to cache the result in seconds
        """
        self.check_host = check_host
        self.check_port = check_port
        self.check_timeout = check_timeout
        self.cache_ttl = cache_ttl

        self._lock = threading.Lock()
        self._last_check_time = 0
        self._last_result = True  # Assume healthy initially
        self._was_healthy = True  # Track previous state for transition logging

    def is_healthy(self):
        """
        Check if network is available. Returns cached result if within TTL.
        Thread-safe.

        Returns:
            bool: True if network is available
        """
        with self._lock:
            now = time.time()
            if now - self._last_check_time < self.cache_ttl:
                return self._last_result

            healthy = self._check_connectivity()
            self._last_check_time = now

            # Log state transitions
            if self._was_healthy and not healthy:
                logging.warning("ネットワーク障害を検知しました (%s:%d への接続失敗)",
                                self.check_host, self.check_port)
            elif not self._was_healthy and healthy:
                logging.info("ネットワーク復帰を検知しました")

            self._was_healthy = healthy
            self._last_result = healthy
            return healthy

    def _check_connectivity(self):
        """Perform actual connectivity check via TCP socket."""
        try:
            sock = socket.create_connection(
                (self.check_host, self.check_port),
                timeout=self.check_timeout
            )
            sock.close()
            return True
        except OSError:
            return False

    def invalidate_cache(self):
        """Force the next call to is_healthy() to perform a fresh check."""
        with self._lock:
            self._last_check_time = 0


class CircuitState(enum.Enum):
    CLOSED = 'closed'
    OPEN = 'open'
    HALF_OPEN = 'half_open'


class CircuitBreaker:
    """
    Circuit breaker pattern implementation.

    CLOSED: Normal operation, requests pass through.
    OPEN: Requests are blocked (fail fast) after consecutive failures.
    HALF_OPEN: After recovery timeout, allow one request to test recovery.
    """

    def __init__(self, name, failure_threshold=3, recovery_timeout=60):
        """
        Args:
            name: Name for logging
            failure_threshold: Number of consecutive failures before opening
            recovery_timeout: Seconds to wait before trying half-open
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0

    @property
    def state(self):
        """Get current state, transitioning OPEN -> HALF_OPEN if timeout elapsed."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    logging.info("サーキットブレーカー[%s]: HALF_OPEN に遷移 (再試行許可)", self.name)
                    self._state = CircuitState.HALF_OPEN
            return self._state

    def allow_request(self):
        """
        Check if a request should be allowed.
        In HALF_OPEN state, only one request is allowed (transitions to OPEN to block others).

        Returns:
            bool: True if the request can proceed
        """
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.HALF_OPEN:
                # Allow one probe request, block subsequent ones until result
                self._state = CircuitState.OPEN
                return True
            # OPEN
            return False

    def record_success(self):
        """Record a successful request. Resets failure count and closes circuit."""
        with self._lock:
            if self._state != CircuitState.CLOSED:
                logging.info("サーキットブレーカー[%s]: CLOSED に遷移 (復旧)", self.name)
            self._failure_count = 0
            self._state = CircuitState.CLOSED

    def record_failure(self):
        """Record a failed request. May open the circuit."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    logging.warning(
                        "サーキットブレーカー[%s]: OPEN に遷移 (連続%d回失敗, %d秒後に再試行)",
                        self.name, self._failure_count, self.recovery_timeout
                    )
                self._state = CircuitState.OPEN


def retry_with_backoff(func=None, max_retries=3, base_delay=1, max_delay=30,
                       network_checker=None):
    """
    Decorator/function for retry with exponential backoff.

    Can be used as decorator:
        @retry_with_backoff(max_retries=3)
        def my_func(): ...

    Or called directly:
        retry_with_backoff(my_func, max_retries=3)()

    Args:
        func: Function to wrap (when used as direct call)
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        network_checker: Optional NetworkHealthChecker instance
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                # Skip if network is down
                if network_checker and not network_checker.is_healthy():
                    logging.warning("ネットワーク不通のため %s をスキップ", fn.__name__)
                    return None

                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logging.warning(
                            "%s 失敗 (試行 %d/%d, %s秒後にリトライ): %s",
                            fn.__name__, attempt + 1, max_retries + 1, delay, e
                        )
                        time.sleep(delay)
                    else:
                        logging.error(
                            "%s 失敗 (全%d回の試行が失敗): %s",
                            fn.__name__, max_retries + 1, e
                        )
            raise last_exception
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator
