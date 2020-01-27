"""Django admin configuration for the Ad Server authentication app."""
from allauth.account.forms import default_token_generator
from allauth.account.utils import user_pk_to_url_str
from django.conf import settings
from django.contrib import admin
from django.contrib import messages
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):

    """Django admin configuration for users."""

    actions = ("invite_user",)
    fieldsets = (
        (None, {"fields": ("email", "name", "password")}),
        (_("Ad server details"), {"fields": ("advertisers", "publishers")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            _("Important dates"),
            {"fields": ("last_login", "updated_date", "created_date")},
        ),
    )
    list_display = (
        "email",
        "name",
        "is_active",
        "is_staff",
        "last_login",
        "created_date",
    )
    list_filter = ("is_active", "is_staff", "is_superuser")
    readonly_fields = ("password", "updated_date", "created_date")
    search_fields = ("email", "name")

    def get_password_reset_url(self, request, user):
        temp_key = default_token_generator.make_token(user)
        path = reverse(
            "account_reset_password_from_key",
            kwargs=dict(uidb36=user_pk_to_url_str(user), key=temp_key),
        )
        return request.build_absolute_uri(path)

    def invite_user(self, request, queryset):
        site = get_current_site(request)
        for user in queryset:
            if user.last_login:
                messages.error(
                    request,
                    _("No invite sent %(user)s. They have already logged in.")
                    % {"user": user},
                )
            else:
                activate_url = self.get_password_reset_url(request, user)
                context = {"user": user, "site": site, "activate_url": activate_url}
                send_mail(
                    _("You've been invited to %(name)s") % {"name": site.name},
                    render_to_string("auth/email/account_invite.txt", context),
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                )
                messages.success(
                    request, _("Sent invite to %(user)s.") % {"user": user}
                )

    invite_user.short_description = _("Invite selected users")
