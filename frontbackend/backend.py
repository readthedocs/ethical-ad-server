"""
Front (front.com) email backend.

There's some differences from normal email:

- There are a few settings:
  * FRONT_TOKEN - the API token used in the Authorization header
  * FRONT_CHANNEL - the Front inbox to use
  * FRONT_AUTHOR - the author for a draft message; ONLY used with drafts
  * FRONT_ARCHIVE (default=False) - whether to archive sent messages
- "From" and "Reply to" aren't used.
  Instead, the from address is set by the channel (FRONT_CHANNEL).
- By appending an attribute "draft" to an email message,
  the backend will create a draft instead of sending the message.
"""

import logging

import requests
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import sanitize_address

from . import settings


log = logging.getLogger(__name__)  # noqa


class EmailBackend(BaseEmailBackend):
    """
    Custom email backend to send messages through Front (front.com).

    See: https://docs.djangoproject.com/en/4.2/topics/email/#defining-a-custom-email-backend
    """

    def __init__(
        self,
        token=None,
        channel=None,
        sender_name=None,
        author=None,
        archive=False,
        **kwargs,
    ):
        """
        Initialize the backend.

        :param token: The Front API token (defaults to settings.FRONT_TOKEN)
        :param channel: The Front channel (defaults to settings.FRONT_CHANNEL)
        :param sender_name: A display name for the FROM address (defaults to settings.FRONT_SENDER_NAME)
        :param author: Used for drafts only to save the draft to a teammate's drafts folder
            (defaults to settings.FRONT_AUTHOR)
        :param archive: Whether to auto-archive sent messages (defaults to settings.FRONT_ARCHIVE)
        """
        super().__init__(**kwargs)

        self.token = token or settings.FRONT_TOKEN
        self.channel = channel or settings.FRONT_CHANNEL

        if not self.token or not self.channel:
            raise NotImplementedError(
                "For the Front email backend, "
                "settings.FRONT_TOKEN and settings.FRONT_CHANNEL "
                "must be set."
            )

        self.sender_name = sender_name or settings.FRONT_SENDER_NAME
        self.author = author or settings.FRONT_AUTHOR

        # Whether to archive messages on send
        self.archive = archive or settings.FRONT_ARCHIVE

        # Front API urls for creating a conversation or creating a draft
        # https://dev.frontapp.com/reference/post_channels-channel-id-messages
        # https://dev.frontapp.com/reference/post_conversations-conversation-id-drafts
        self.message_url = f"https://api2.frontapp.com/channels/{self.channel}/messages"
        self.draft_url = f"https://api2.frontapp.com/channels/{self.channel}/drafts"

        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def send_messages(self, email_messages):
        """Write all messages to the stream in a thread-safe way."""
        if not email_messages:
            return 0

        num_sent = 0
        for message in email_messages:
            sent = self._send(message)
            if sent:
                num_sent += 1

        return num_sent

    def _send(self, email_message):
        """A helper method that does the actual sending through the Front API."""
        if not email_message.recipients():
            return False

        # Whether this email should be created as a draft or simply sent (the default)
        draft = getattr(email_message, "draft", False)

        # Whether to archive this message when sent
        archive = getattr(email_message, "archive", self.archive)

        encoding = email_message.encoding or settings.DEFAULT_CHARSET
        recipients = [
            sanitize_address(addr, encoding) for addr in email_message.recipients()
        ]

        if email_message.attachments:
            log.warning("Front email backend does not yet implement attachments!")

        payload = {
            "to": recipients,
            "cc": email_message.cc,
            "bcc": email_message.bcc,
            "sender_name": self.sender_name,
            "subject": email_message.subject,
            "options": {"archive": archive},
            "body": email_message.body,
        }

        if draft:
            url = self.draft_url
            payload["mode"] = "shared"
            payload["author_id"] = self.author
            if not self.author:
                raise NotImplementedError(
                    "Can't save a draft message without setting FRONT_AUTHOR."
                )
            log.debug("Creating Front draft message: %s", email_message.subject)
        else:
            url = self.message_url
            log.debug("Starting Front conversation: %s", email_message.subject)

        response = requests.post(url, json=payload, headers=self.headers)

        if response.ok:
            return True

        if not self.fail_silently:
            log.error(
                "Failed to send front message: %s, to=%s", response.content, recipients
            )
            response.raise_for_status()

        return False
