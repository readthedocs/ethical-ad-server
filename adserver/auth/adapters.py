"""Adapters to control Django-allauth for the ad server."""

from allauth.account.adapter import DefaultAccountAdapter


class AdServerAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        """Open user registration is disabled."""
        return False  # pragma: no cover
