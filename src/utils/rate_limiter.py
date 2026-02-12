"""API rate limiting utility for Fingerprint Flow."""

from __future__ import annotations

import threading
import time

from src.utils.logger import get_logger

logger = get_logger("utils.rate_limiter")


class RateLimiter:
    """Thread-safe rate limiter that enforces minimum intervals between calls.

    Uses per-service locks so that waiting on one service does not block
    requests to a different service.

    Usage:
        limiter = RateLimiter()
        limiter.wait("musicbrainz", 1.0)  # Waits if needed to respect 1 req/sec
    """

    def __init__(self) -> None:
        self._last_call: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._meta_lock = threading.Lock()  # protects _locks dict creation

    def _get_lock(self, service_name: str) -> threading.Lock:
        """Get or create a per-service lock."""
        if service_name not in self._locks:
            with self._meta_lock:
                # Double-check after acquiring meta lock
                if service_name not in self._locks:
                    self._locks[service_name] = threading.Lock()
        return self._locks[service_name]

    def wait(self, service_name: str, min_interval: float) -> None:
        """Block until enough time has passed since the last call to this service.

        Args:
            service_name: Identifier for the API service (e.g. "musicbrainz").
            min_interval: Minimum seconds between requests.
        """
        lock = self._get_lock(service_name)

        with lock:
            now = time.monotonic()
            last = self._last_call.get(service_name, 0.0)
            elapsed = now - last
            sleep_time = 0.0
            if elapsed < min_interval:
                sleep_time = min_interval - elapsed

        # Sleep OUTSIDE the lock so other services aren't blocked
        if sleep_time > 0:
            logger.debug("Rate limit: sleeping %.2fs for %s", sleep_time, service_name)
            time.sleep(sleep_time)

        # Re-acquire to stamp the actual call time
        with lock:
            self._last_call[service_name] = time.monotonic()


# Global singleton for shared rate limiting across modules
rate_limiter = RateLimiter()
