"""Settings used in testing."""
import warnings

from .development import *  # noqa


# Ignore whitenoise message about no static directory
warnings.filterwarnings("ignore", message="No directory at", module="whitenoise.base")

TESTING = True
TEMPLATES[0]["OPTIONS"]["debug"] = DEBUG
LOGGING["loggers"]["adserver"]["level"] = "CRITICAL"

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
