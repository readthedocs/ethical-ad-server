"""Ethical Ad Server."""
from .celery import app as celery_app  # noqa


default_app_config = "adserver.apps.AdserverConfig"
