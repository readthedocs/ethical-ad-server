"""
Production Django settings for the Ethical Ad Server project.

This is meant to be customized by setting environment variables.

Only a few environment variables are required:

- SECRET_KEY
- ALLOWED_HOSTS
- REDIS_URL
- DATABASE_URL
- SENDGRID_API_KEY
"""

import logging
import socket
import ssl

from celery.schedules import crontab

from .base import *  # noqa
from .base import env


# Django Settings
# https://docs.djangoproject.com/en/dev/ref/settings/
# --------------------------------------------------------------------------
DEBUG = False
TEMPLATE_DEBUG = DEBUG

# ALLOWED_HOSTS is required in production
# eg. "adserver.yourserver.com,adserver.yourserver.io"
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
SECRET_KEY = env("SECRET_KEY")  # Django won't start unless the SECRET_KEY is non-empty
INTERNAL_IPS = env.list("INTERNAL_IPS", default=[])


# Database
# https://docs.djangoproject.com/en/dev/ref/settings/#databases
# --------------------------------------------------------------------------
DATABASES["default"] = env.db()  # Raises ImproperlyConfigured if DATABASE_URL not set

# Enable database connection pooling
# https://docs.djangoproject.com/en/dev/ref/databases/#connection-pool
USE_DB_POOLING = env.bool("USE_DB_POOLING", default=False)
for db in ("default", "replica"):
    if db in DATABASES:
        # https://docs.djangoproject.com/en/dev/topics/db/transactions/#tying-transactions-to-http-requests
        DATABASES[db]["ATOMIC_REQUESTS"] = True

        if "OPTIONS" not in DATABASES[db]:
            DATABASES[db]["OPTIONS"] = {}

        if (
            DATABASES[db]["ENGINE"] == "django.db.backends.postgresql"
            and USE_DB_POOLING
        ):
            DATABASES[db]["OPTIONS"]["pool"] = True
        else:
            # CONN_MAX_AGE should be 0 when using connection pooling
            DATABASES[db]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=3600)


# Logging changes
# --------------------------------------------------------------------------
# Folks spam our site with random hosts all the time. Ignore these errors.
LOGGING["loggers"]["django.security.DisallowedHost"] = {
    "handlers": ["null"],
    "propagate": False,
}

# The analyzer can log very verbosely on error URLs
LOGGING["loggers"]["trafilatura.downloads"] = {
    "handlers": ["null"],
    "propagate": False,
}
LOGGING["loggers"]["trafilatura.core"] = {
    "handlers": ["null"],
    "propagate": False,
}


# Cache
# https://docs.djangoproject.com/en/dev/topics/cache/
# https://github.com/jazzband/django-redis
# --------------------------------------------------------------------------
CACHES["default"] = env.cache("REDIS_URL")

# Secure connection workaround
# https://github.com/joke2k/django-environ/pull/211
if env.bool("REDIS_SSL", default=False):
    CACHES["default"]["LOCATION"] = CACHES["default"]["LOCATION"].replace(
        "redis://", "rediss://"
    )


# Security
# https://docs.djangoproject.com/en/dev/topics/security/
# https://docs.djangoproject.com/en/dev/ref/middleware/#django.middleware.security.SecurityMiddleware
# https://docs.djangoproject.com/en/dev/ref/clickjacking/
# --------------------------------------------------------------------------
if env.bool("ADSERVER_HTTPS", default=False):
    ADSERVER_HTTPS = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365  # 1 year is recommended: 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    # Redirect HTTP -> HTTPS
    # https://devcenter.heroku.com/articles/http-routing#heroku-headers
    # Optionally enforce a specific host. Other hosts will redirect
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True

    # Enforcing the host means any request for any other host will redirect
    # Don't do this on ethicalads-extra (our staging server)
    if not socket.gethostname().startswith("ethicalads-extra"):
        ENFORCE_HOST = env("ENFORCE_HOST", default=None)

# Email settings
# See: https://anymail.readthedocs.io
# --------------------------------------------------------------------------
INSTALLED_APPS += ["anymail"]
EMAIL_BACKEND = "anymail.backends.sendgrid.EmailBackend"
ANYMAIL = {"SENDGRID_API_KEY": env("SENDGRID_API_KEY")}


# User upload storage
# https://docs.djangoproject.com/en/dev/topics/files/
# https://django-storages.readthedocs.io/en/latest/backends/azure.html
STORAGES["default"]["BACKEND"] = env(
    "DEFAULT_FILE_STORAGE", default="storages.backends.azure_storage.AzureStorage"
)
STORAGES["default"]["OPTIONS"] = {}
custom_domain = env("DEFAULT_FILE_STORAGE_HOSTNAME", default=None)
if custom_domain:
    STORAGES["default"]["OPTIONS"]["custom_domain"] = custom_domain
MEDIA_URL = env("MEDIA_URL", default="")
MEDIA_ROOT = env("MEDIA_ROOT", default="")
AZURE_ACCOUNT_NAME = env("AZURE_ACCOUNT_NAME", default="")
AZURE_ACCOUNT_KEY = env("AZURE_ACCOUNT_KEY", default="")
AZURE_CONTAINER = env("AZURE_CONTAINER", default="")
BACKUPS_STORAGE = env("BACKUPS_STORAGE", default="config.storage.AzureBackupsStorage")
STORAGES["backups"] = {"BACKEND": BACKUPS_STORAGE}


# Celery settings for asynchronous tasks
# http://docs.celeryproject.org
# --------------------------------------------------------------------------
CELERY_TASK_ALWAYS_EAGER = False
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=env("REDIS_URL"))
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

# This setting means that workers should acknowledge a task after it is executed
# https://docs.celeryq.dev/page/userguide/configuration.html#std:setting-task_acks_late
CELERY_ACKS_LATE = True

if env.bool("REDIS_SSL", default=False):
    CELERY_BROKER_URL = CELERY_BROKER_URL.replace("redis://", "rediss://")
    CELERY_RESULT_BACKEND = CELERY_BROKER_URL
    CELERY_REDIS_BACKEND_USE_SSL = {"ssl_cert_reqs": ssl.CERT_REQUIRED}
    CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": ssl.CERT_REQUIRED}

CELERY_BEAT_SCHEDULE = {
    # Run the previous days reports
    "every-day-generate-indexes-all-reports": {
        "task": "adserver.tasks.update_previous_day_reports",
        "schedule": crontab(hour="2", minute="30"),
    },
    "every-day-calculate-publisher-ctrs": {
        "task": "adserver.tasks.calculate_publisher_ctrs",
        "schedule": crontab(hour="3", minute="30"),
    },
    "every-day-calculate-ad-ctrs": {
        "task": "adserver.tasks.calculate_ad_ctrs",
        "schedule": crontab(hour="3", minute="35"),
    },
    "every-day-notify-completed-flights": {
        "task": "adserver.tasks.notify_of_completed_flights",
        "schedule": crontab(hour="5", minute="0"),
    },
    "every-day-notify-auto-renewing-flights": {
        "task": "adserver.tasks.notify_of_autorenewing_flights",
        "schedule": crontab(hour="5", minute="30"),
    },
    "every-day-new-advertiser-flight-launched": {
        "task": "adserver.tasks.notify_of_first_flight_launched",
        "schedule": crontab(hour="1", minute="30"),
    },
    "every-week-notify-publisher-changes": {
        "task": "adserver.tasks.notify_of_publisher_changes",
        # Runs on Wednesday
        "schedule": crontab(day_of_week=3, hour="5", minute="0"),
    },
    "every-week-disable-inactive-publishers": {
        "task": "adserver.tasks.disable_inactive_publishers",
        # Runs on Tuesday
        "schedule": crontab(day_of_week=2, hour="6", minute="0"),
    },
    "every-week-remove-old-report-data": {
        "task": "adserver.tasks.remove_old_report_data",
        # Runs on Wednesday
        "schedule": crontab(day_of_week=3, hour="5", minute="10"),
    },
    # Very fast indexes that can be run more frequently
    "halfhourly-advertiser-index": {
        "task": "adserver.tasks.daily_update_advertisers",
        "schedule": crontab(minute="*/5"),
    },
    "halfhourly-publisher-index": {
        "task": "adserver.tasks.daily_update_publishers",
        "schedule": crontab(minute="*/30"),
    },
    "frequent-refresh-flight-totals": {
        "task": "adserver.tasks.refresh_flight_denormalized_totals",
        "schedule": crontab(minute="*/5"),  # Every 5 minutes
    },
    # Run publisher importers daily
    "every-day-sync-publisher-data": {
        "task": "adserver.tasks.run_publisher_importers",
        "schedule": crontab(hour="1", minute="0"),
    },
}

# Tasks which should only be run if the analyzer is installed
if "adserver.analyzer" in INSTALLED_APPS:
    CELERY_BEAT_SCHEDULE["every-day-visited-urls"] = {
        "task": "adserver.analyzer.tasks.daily_visited_urls_aggregation",
        "schedule": crontab(hour="3", minute="0"),
    }
    CELERY_BEAT_SCHEDULE["every-day-analyze-urls"] = {
        "task": "adserver.analyzer.tasks.daily_analyze_urls",
        "schedule": crontab(hour="4", minute="0"),
    }
    CELERY_BEAT_SCHEDULE["every-week-domain-centroids"] = {
        "task": "adserver.analyzer.tasks.update_domain_centroids",
        "schedule": crontab(day_of_week=6, hour="1", minute="10"),
    }
if "ethicalads_ext.embedding" in INSTALLED_APPS:
    CELERY_BEAT_SCHEDULE["every-day-analyze-advertiser-urls"] = {
        "task": "ethicalads_ext.embedding.tasks.daily_analyze_advertiser_urls",
        "schedule": crontab(hour="4", minute="30"),
    }
if "ethicalads_ext.etl" in INSTALLED_APPS:
    CELERY_BEAT_SCHEDULE["every-day-etl-pipeline"] = {
        "task": "ethicalads_ext.etl.tasks.daily_etl_pipeline",
        "schedule": crontab(hour="2", minute="0"),
    }


# Sentry settings for error monitoring
# https://docs.sentry.io/platforms/python/django/
# --------------------------------------------------------------------------
SENTRY_DSN = env("SENTRY_DSN", default=None)
if SENTRY_DSN:
    # pylint: disable=import-error
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.logging import ignore_logger
    from sentry_sdk.integrations.redis import RedisIntegration

    sentry_logging = LoggingIntegration(
        event_level=logging.WARNING  # Send warnings as events
    )
    ignore_logger("django.security.DisallowedHost")

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            sentry_logging,
            # https://docs.sentry.io/platforms/python/integrations/django/#options
            DjangoIntegration(),
            # https://docs.sentry.io/platforms/python/integrations/celery/#options
            CeleryIntegration(),
            # https://docs.sentry.io/platforms/python/integrations/redis/#options
            RedisIntegration(),
        ],
        # Enable tracing and profiling but with sampling
        # Setting a value of 1.0 will send 100% of traces to Sentry
        # https://docs.sentry.io/platforms/python/tracing/
        traces_sample_rate=env.float("SENTRY_TRACING_SAMPLE_RATE", default=0.2),
        # https://docs.sentry.io/platforms/python/profiling/
        profiles_sample_rate=env.float("SENTRY_PROFILES_SAMPLE_RATE", default=0.05),
    )


# Production ad server specific settings
# https://ethical-ad-server.readthedocs.io/en/latest/install/configuration.html
# --------------------------------------------------------------------------
ADSERVER_ADMIN_URL = env("ADSERVER_ADMIN_URL", default="admin")
ADSERVER_DO_NOT_TRACK = env.bool("ADSERVER_DO_NOT_TRACK", default=False)
ADSERVER_RECORD_VIEWS = env.bool("ADSERVER_RECORD_VIEWS", default=False)
ADSERVER_CLICK_RATELIMITS = env.list(
    "ADSERVER_CLICK_RATELIMITS", default=["1/m", "3/10m", "10/h", "25/d"]
)
ADSERVER_VIEW_RATELIMITS = env.list("ADSERVER_VIEW_RATELIMITS", default=["5/5m"])
ADSERVER_STICKY_DECISION_DURATION = env.int(
    "ADSERVER_STICKY_DECISION_DURATION", default=5
)

# GeoIP settings
# This directory should be the path to GeoLite2-City.mmdb and GeoLite2-Country.mmdb
GEOIP_PATH = env("GEOIP_GEOLITE2_PATH", default=GEOIP_PATH)
GEOIP_CITY = env("GEOIP_GEOLITE2_CITY_FILENAME", default="GeoLite2-City.mmdb")
GEOIP_COUNTRY = env("GEOIP_GEOLITE2_COUNTRY_FILENAME", default="GeoLite2-Country.mmdb")

# Stripe settings for dj-stripe
STRIPE_LIVE_MODE = True
