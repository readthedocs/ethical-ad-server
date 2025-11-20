"""Tests for health check endpoints."""

from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone


class FlightTotalsHealthTest(TestCase):
    """Tests for the flight totals health check endpoint."""

    def setUp(self):
        """Clear cache before each test."""
        cache.clear()

    def test_health_check_no_cache(self):
        """Test health check returns 503 when task has never run."""
        response = self.client.get(reverse("health-flight-totals"))
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("never run", data["message"])

    def test_health_check_recent_run(self):
        """Test health check returns 200 when task ran recently."""
        # Set cache to indicate task ran 5 minutes ago
        cache.set("flight_totals_last_refresh", timezone.now().isoformat())

        response = self.client.get(reverse("health-flight-totals"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertLessEqual(data["minutes_since_refresh"], 1)

    def test_health_check_stale_run(self):
        """Test health check returns 503 when task hasn't run in a while."""
        # Set cache to indicate task ran 30 minutes ago (stale)
        stale_time = timezone.now() - timedelta(minutes=30)
        cache.set("flight_totals_last_refresh", stale_time.isoformat())

        response = self.client.get(reverse("health-flight-totals"))
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertGreater(data["minutes_since_refresh"], 20)

    def test_health_check_invalid_timestamp(self):
        """Test health check returns 503 when cache contains invalid data."""
        cache.set("flight_totals_last_refresh", "invalid-timestamp")

        response = self.client.get(reverse("health-flight-totals"))
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("Invalid timestamp", data["message"])
