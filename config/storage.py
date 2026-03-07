"""
Django storage classes and mixins for custom storage backends.

Supports both Azure Blob Storage and AWS S3.
Configured via DEFAULT_FILE_STORAGE and related envvars.
See config/settings/production.py.
"""

from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from django.conf import settings


class OverrideHostnameMixin:
    """
    Override the hostname when outputting URLs.

    This is useful for use with a CDN or when proxying outside of Blob Storage / S3.

    See: https://github.com/jschneier/django-storages/pull/658
    """

    # Just the hostname without scheme (eg. 'media.ethicalads.io')
    override_hostname = None

    def url(self, *args, **kwargs):
        url = super().url(*args, **kwargs)

        if self.override_hostname:
            parts = list(urlsplit(url))
            parts[1] = self.override_hostname
            url = urlunsplit(parts)

        return url


# ---- Azure backends (legacy) ------------------------------------------------
try:
    from storages.backends.azure_storage import AzureStorage  # noqa

    class AzureCDNFileStorage(OverrideHostnameMixin, AzureStorage):
        """An Azure Storage backend that uses a CDN and custom hostname for media."""

        override_hostname = getattr(settings, "DEFAULT_FILE_STORAGE_HOSTNAME", None)

    class AzureBackupsStorage(AzureStorage):
        """An Azure Storage backend for backups."""

        azure_container = (
            getattr(settings, "AZURE_BACKUPS_STORAGE_CONTAINER", None) or "backups"
        )

except ImportError:
    pass


# ---- AWS S3 backends --------------------------------------------------------
try:
    from storages.backends.s3boto3 import S3Boto3Storage

    class S3CDNFileStorage(OverrideHostnameMixin, S3Boto3Storage):
        """An S3 storage backend that uses CloudFront and a custom hostname for media."""

        override_hostname = getattr(settings, "DEFAULT_FILE_STORAGE_HOSTNAME", None)

    class S3BackupsStorage(S3Boto3Storage):
        """An S3 storage backend for database backups."""

        bucket_name = getattr(settings, "AWS_BACKUPS_STORAGE_BUCKET_NAME", None) or (
            f"{getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'ethicalads')}-backups"
        )

except ImportError:
    pass
