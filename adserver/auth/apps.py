"""App config for ad server auth."""

from django.apps import AppConfig


def pw_reset_callback(sender, request, user, **kwargs):
    """Mark the email verified after a PW reset (includes invite)"""
    for email in user.emailaddress_set.filter(email=user.email):
        email.set_verified()


class AdServerAuthConfig(AppConfig):
    name = "adserver.auth"
    label = "adserver_auth"
    verbose_name = "Ad Server Auth"

    def ready(self):
        from allauth.account.signals import password_reset  # noqa

        password_reset.connect(pw_reset_callback)
