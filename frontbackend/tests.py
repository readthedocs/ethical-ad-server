from unittest import mock

import requests
import responses
from django.core import mail
from django.test import TestCase

from .backend import EmailBackend


class FrontEmailBackendTestCase(TestCase):
    def setUp(self):
        super().setUp()

        self.channel = "cha_XXX"
        self.token = "fake-token"
        self.sender_name = "Sender Name"
        self.archive = True
        self.author = "tea_XXX"

        self.message = mail.EmailMessage(
            "Test subject",
            "This is a test body",
            "noreply@ethicalads.io",  # From (not used)
            ["test@ethicalads.io"],  # To
        )

    def test_bad_setup(self):
        with self.assertRaises(NotImplementedError):
            self.backend = EmailBackend()

    @responses.activate
    def test_send_message(self):
        with mock.patch("frontbackend.backend.settings") as front_settings:
            front_settings.FRONT_CHANNEL = self.channel
            front_settings.FRONT_TOKEN = self.token
            front_settings.FRONT_SENDER_NAME = self.sender_name
            front_settings.FRONT_ARCHIVE = self.archive

            self.backend = EmailBackend()

            self.assertEqual(self.backend.send_messages([]), 0)

            responses.add(
                responses.POST,
                f"https://api2.frontapp.com/channels/{self.channel}/messages",
            )
            self.assertEqual(self.backend.send_messages([self.message]), 1)

            # Test with attachments (not currently implemented)
            self.message.attach("test.txt", b"123", "text/plain")
            self.assertEqual(self.backend.send_messages([self.message]), 1)

    @responses.activate
    def test_send_message_failure(self):
        with mock.patch("frontbackend.backend.settings") as front_settings:
            front_settings.FRONT_CHANNEL = self.channel
            front_settings.FRONT_TOKEN = self.token
            front_settings.FRONT_SENDER_NAME = self.sender_name
            front_settings.FRONT_ARCHIVE = self.archive

            self.backend = EmailBackend(fail_silently=True)

            # No recipients (no http request, etc.)
            self.message.to = []
            self.assertEqual(self.backend.send_messages([self.message]), 0)

            self.message.to = ["test@ethicalads.io"]

            # Fail silently
            responses.add(
                responses.POST,
                f"https://api2.frontapp.com/channels/{self.channel}/messages",
                status=400,
            )
            self.assertEqual(self.backend.send_messages([self.message]), 0)

            # Fail LOUDLY
            self.backend = EmailBackend(fail_silently=False)
            responses.reset()
            responses.add(
                responses.POST,
                f"https://api2.frontapp.com/channels/{self.channel}/messages",
                status=400,
            )
            with self.assertRaises(requests.RequestException):
                self.backend.send_messages([self.message])

    @responses.activate
    def test_create_draft(self):
        with mock.patch("frontbackend.backend.settings") as front_settings:
            front_settings.FRONT_CHANNEL = self.channel
            front_settings.FRONT_TOKEN = self.token
            front_settings.FRONT_SENDER_NAME = self.sender_name
            front_settings.FRONT_ARCHIVE = self.archive
            front_settings.FRONT_AUTHOR = self.author

            self.backend = EmailBackend()

            self.message.draft = True

            responses.add(
                responses.POST,
                f"https://api2.frontapp.com/channels/{self.channel}/drafts",
            )
            self.assertEqual(self.backend.send_messages([self.message]), 1)
