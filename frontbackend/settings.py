"""
Default settings for the Front email backend.

These can be overridden when initializing the backend.
"""
from django.conf import settings


# The FRONT_TOKEN is the token set in the authorization header
# Do not include the phrase "Bearer".
# https://dev.frontapp.com/docs/authentication
FRONT_TOKEN = getattr(settings, "FRONT_TOKEN", None)

# FRONT_CHANNEL should be the channel ID in front.
# This usually should be of the form `cha_XXX`.
# Retrieve a list of channels with
# https://dev.frontapp.com/reference/get_channels
FRONT_CHANNEL = getattr(settings, "FRONT_CHANNEL", None)

# FRONT_SENDER_NAME customizes the display of the sender
# If not set, it will be the default for the channel
FRONT_SENDER_NAME = getattr(settings, "FRONT_SENDER_NAME", None)

# The author for a draft message
# This is *ONLY* used when saving drafts
# This should be set to a "Teammate ID"
# https://dev.frontapp.com/reference/get_teammates
FRONT_AUTHOR = getattr(settings, "FRONT_AUTHOR", None)

# Whether to archive messages after they are sent
FRONT_ARCHIVE = getattr(settings, "FRONT_ARCHIVE", False)

# This is just a setting from Django used in the backend
# https://docs.djangoproject.com/en/3.2/ref/settings/#default-charset
DEFAULT_CHARSET = settings.DEFAULT_CHARSET
