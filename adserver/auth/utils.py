from allauth.account.forms import default_token_generator
from allauth.account.utils import user_pk_to_url_str
from django.conf import settings
from django.contrib import messages
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


def invite_user(queryset, request=None, message=True):
    site = get_current_site(request)
    for user in queryset:
        if user.last_login:
            if request and message:
                messages.error(
                    request,
                    _("No invite sent %(user)s. They have already logged in.")
                    % {"user": user},
                )
            else:
                return False
        else:
            activate_url = get_password_reset_url(request, user)
            context = {"user": user, "site": site, "activate_url": activate_url}
            send_mail(
                _("You've been invited to %(name)s") % {"name": site.name},
                render_to_string("auth/email/account_invite.txt", context),
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
            )
            if request and message:
                messages.success(
                    request, _("Sent invite to %(user)s.") % {"user": user}
                )
            else:
                return True


def get_password_reset_url(request, user):
    temp_key = default_token_generator.make_token(user)
    path = reverse(
        "account_reset_password_from_key",
        kwargs=dict(uidb36=user_pk_to_url_str(user), key=temp_key),
    )
    return request.build_absolute_uri(path)
