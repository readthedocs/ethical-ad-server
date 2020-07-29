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

# Set the GeoIP path to something that doesn't exist
# This will ensure that the test suite matches what's run in CI
# There will be no IP geolocation done in testing
GEOIP_PATH = os.path.join(BASE_DIR, "geoip-noexists")
