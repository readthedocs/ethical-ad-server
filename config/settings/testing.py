"""Settings used in testing."""

import os
import warnings

from .development import *  # noqa


# Ignore whitenoise message about no static directory
warnings.filterwarnings("ignore", message="No directory at", module="whitenoise.base")

TESTING = True
TEMPLATES[0]["OPTIONS"]["debug"] = DEBUG
LOGGING["loggers"][""]["level"] = "CRITICAL"
LOGGING["loggers"]["adserver"]["level"] = "CRITICAL"
LOGGING["loggers"]["ethicalads_ext"]["level"] = "CRITICAL"

# Skip the ext apps in testing unless explicitly enabled
TESTING_EXT = bool(os.getenv("TESTING_EXT", default=False))
if "ethicalads_ext.embedding" in INSTALLED_APPS and not TESTING_EXT:
    print("Skipping ethicalads_ext.embedding in testing")
    INSTALLED_APPS.remove("ethicalads_ext.embedding")
if "ethicalads_ext.etl" in INSTALLED_APPS and not TESTING_EXT:
    INSTALLED_APPS.remove("ethicalads_ext.etl")

# Set the analyzer explicitly in testing
ADSERVER_ANALYZER_BACKEND = [
    "adserver.analyzer.backends.naive.NaiveKeywordAnalyzerBackend"
]
if "adserver.analyzer" not in INSTALLED_APPS:
    INSTALLED_APPS.append("adserver.analyzer")

# Whitenoise relies on the manifest being present.
# Which may not be there in testing
# unless you run `collectstatic` before running tests
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

# Always use in-memory cache for testing
CACHES["default"] = {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "",
}

# Celery should be always eager - there's no distributed celery workers in test
CELERY_TASK_ALWAYS_EAGER = True

# Set the GeoIP path to something that doesn't exist
# This will ensure that the test suite matches what's run in CI
# There will be no IP geolocation done in testing
GEOIP_PATH = os.path.join(BASE_DIR, "geoip-noexists")

# By setting a testing backend, this allows verifying these messages
# from unit tests
# https://django-slack.readthedocs.io/#testing
SLACK_BACKEND = "django_slack.backends.TestBackend"
SLACK_TOKEN = "this-is-a-test-token"
