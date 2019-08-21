from .base import *  # noqa


TESTING = True
TEMPLATES[0]["OPTIONS"]["debug"] = DEBUG
LOGGING["loggers"]["adserver"]["level"] = "ERROR"
