"""Ethical Ad Server"""
from .celery import app as celery_app


default_app_config = "adserver.apps.AdserverConfig"
