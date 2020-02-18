"""Settings used in testing."""
import warnings

from .development import *  # noqa


# Ignore whitenoise message about no static directory
warnings.filterwarnings("ignore", message="No directory at", module="whitenoise.base")

TESTING = True
TEMPLATES[0]["OPTIONS"]["debug"] = DEBUG
LOGGING["loggers"]["adserver"]["level"] = "ERROR"

# Whitenoise relies on the manifest being present.
# Which may not be there in testing
# unless you run `collectstatic` before running tests
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"
