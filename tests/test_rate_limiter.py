"""Tests for the rate limiter utility."""

from __future__ import annotations

import time
import threading

import pytest

from src.utils.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_first_call_does_not_sleep(self):
        limiter = RateLimiter()
        start = time.monotonic()
        limiter.wait("test_service", 1.0)
        elapsed = time.monotonic() - start
        # First call should be nearly instant
        assert elapsed < 0.5

    def test_second_call_sleeps(self):
        limiter = RateLimiter()
        limiter.wait("test_service", 0.3)
        start = time.monotonic()
        limiter.wait("test_service", 0.3)
        elapsed = time.monotonic() - start
        # Should have slept ~0.3s
        assert elapsed >= 0.2

    def test_different_services_independent(self):
        limiter = RateLimiter()
        limiter.wait("service_a", 1.0)
        # Service B should not have to wait for service A
        start = time.monotonic()
        limiter.wait("service_b", 1.0)
        elapsed = time.monotonic() - start
        assert elapsed < 0.5

    def test_thread_safety(self):
        """Multiple threads using different services should not deadlock."""
        limiter = RateLimiter()
        results = []

        def worker(service_name: str):
            limiter.wait(service_name, 0.1)
            results.append(service_name)

        threads = [
            threading.Thread(target=worker, args=(f"svc_{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(results) == 5
