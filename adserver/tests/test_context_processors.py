import datetime
import unittest.mock

from django.test import RequestFactory
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone

from config.context_processors import maintenance_message_processor


class MaintenanceMessageProcessorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/")

    @override_settings(
        ADSERVER_MAINTENANCE_MESSAGE="System will be down for maintenance at midnight.",
        ADSERVER_MAINTENANCE_MESSAGE_EXPIRY="2027-01-01T00:00:00Z",
    )
    def test_message_shown_before_expiry_string(self):
        # Time is before expiry
        now = timezone.make_aware(datetime.datetime(2026, 12, 31, 23, 0, 0))
        with override_settings(USE_TZ=True):
            with unittest.mock.patch("django.utils.timezone.now", return_value=now):
                context = maintenance_message_processor(self.request)

        self.assertIn("maintenance_message", context)
        self.assertEqual(
            context["maintenance_message"],
            "System will be down for maintenance at midnight.",
        )

    @override_settings(
        ADSERVER_MAINTENANCE_MESSAGE="System will be down for maintenance at midnight.",
        ADSERVER_MAINTENANCE_MESSAGE_EXPIRY="2025-01-01T00:00:00Z",
    )
    def test_message_hidden_after_expiry_string(self):
        # Time is after expiry
        now = timezone.make_aware(datetime.datetime(2026, 1, 1, 0, 0, 0))
        with override_settings(USE_TZ=True):
            with unittest.mock.patch("django.utils.timezone.now", return_value=now):
                context = maintenance_message_processor(self.request)

        self.assertNotIn("maintenance_message", context)

    @override_settings(
        ADSERVER_MAINTENANCE_MESSAGE="System down soon.",
        ADSERVER_MAINTENANCE_MESSAGE_EXPIRY=datetime.datetime(
            2027, 2, 1, tzinfo=datetime.timezone.utc
        ),
    )
    def test_message_shown_before_expiry_datetime(self):
        now = timezone.make_aware(datetime.datetime(2027, 1, 31, 23, 0, 0))
        with override_settings(USE_TZ=True):
            with unittest.mock.patch("django.utils.timezone.now", return_value=now):
                context = maintenance_message_processor(self.request)

        self.assertIn("maintenance_message", context)
        self.assertEqual(context["maintenance_message"], "System down soon.")

    @override_settings(
        ADSERVER_MAINTENANCE_MESSAGE="System down soon.",
        ADSERVER_MAINTENANCE_MESSAGE_EXPIRY=datetime.datetime(
            2025, 2, 1, tzinfo=datetime.timezone.utc
        ),
    )
    def test_message_hidden_after_expiry_datetime(self):
        now = timezone.make_aware(datetime.datetime(2026, 1, 31, 23, 0, 0))
        with override_settings(USE_TZ=True):
            with unittest.mock.patch("django.utils.timezone.now", return_value=now):
                context = maintenance_message_processor(self.request)

        self.assertNotIn("maintenance_message", context)

    @override_settings(
        ADSERVER_MAINTENANCE_MESSAGE="System down soon.",
        ADSERVER_MAINTENANCE_MESSAGE_EXPIRY=None,
    )
    def test_missing_expiry(self):
        # If there's no expiry, the message does not expire and is shown
        context = maintenance_message_processor(self.request)
        self.assertIn("maintenance_message", context)
        self.assertEqual(context["maintenance_message"], "System down soon.")

    @override_settings(
        ADSERVER_MAINTENANCE_MESSAGE=None,
        ADSERVER_MAINTENANCE_MESSAGE_EXPIRY="2027-01-01T00:00:00Z",
    )
    def test_missing_message(self):
        context = maintenance_message_processor(self.request)
        self.assertNotIn("maintenance_message", context)

    @override_settings(
        ADSERVER_MAINTENANCE_MESSAGE="System down soon.",
        ADSERVER_MAINTENANCE_MESSAGE_EXPIRY=datetime.datetime(
            2027, 2, 1
        ),  # Naive datetime
    )
    def test_naive_datetime_expiry(self):
        now = timezone.make_aware(datetime.datetime(2027, 1, 31, 23, 0, 0))
        with override_settings(USE_TZ=True):
            with unittest.mock.patch("django.utils.timezone.now", return_value=now):
                context = maintenance_message_processor(self.request)

        self.assertIn("maintenance_message", context)
        self.assertEqual(context["maintenance_message"], "System down soon.")
