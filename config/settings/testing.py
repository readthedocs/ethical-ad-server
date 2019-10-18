from .development import *  # noqa


TESTING = True
TEMPLATES[0]["OPTIONS"]["debug"] = DEBUG
LOGGING["loggers"]["adserver"]["level"] = "ERROR"

# Whitenoise relies on the manifest being present.
# Which may not be there in testing
# unless you run `collectstatic` before running tests
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"
