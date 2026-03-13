"""
Django storage classes and mixins for custom storage backends (Azure blob storage).

By default, this is not used but it can be configured by setting the
DEFAULT_FILE_STORAGE and DEFAULT_FILE_STORAGE_HOSTNAME envvars.
See config/settings/production.py.
"""

from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from django.conf import settings
from storages.backends.azure_storage import AzureStorage
from storages.backends.s3 import S3Storage


class OverrideHostnameMixin:
    """
    Override the hostname when outputting URLs.

    This is useful for use with a CDN or when proxying outside of Blob Storage

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


class AzureCDNFileStorage(OverrideHostnameMixin, AzureStorage):
    """An Azure Storage backend that uses a CDN and custom hostname for media."""

    override_hostname = getattr(settings, "DEFAULT_FILE_STORAGE_HOSTNAME", None)


class AzureBackupsStorage(AzureStorage):
    """An Azure Storage backend for backups."""

    azure_container = (
        getattr(settings, "AZURE_BACKUPS_STORAGE_CONTAINER", None) or "backups"
    )


class S3CDNFileStorage(OverrideHostnameMixin, S3Storage):
    """An S3 Storage backend that uses a CDN and custom hostname for media."""

    override_hostname = getattr(settings, "DEFAULT_FILE_STORAGE_HOSTNAME", None)
    bucket_name = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None)


class S3BackupsStorage(S3Storage):
    """An S3 Storage backend for backups."""

    bucket_name = getattr(settings, "AWS_BACKUPS_STORAGE_BUCKET_NAME", None)
