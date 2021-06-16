"""Django admin configuration for the Ad Server authentication app."""
from django.contrib import admin
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from simple_history.admin import SimpleHistoryAdmin

from .models import User


@admin.register(User)
class UserAdmin(SimpleHistoryAdmin):

    """Django admin configuration for users."""

    actions = ("invite_user_action",)
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

    def invite_user_action(self, request, queryset):
        for user in queryset:
            if user.invite_user():
                messages.success(
                    request, _("Sent invite to %(user)s.") % {"user": user}
                )
            else:
                messages.error(
                    request,
                    _(
                        "No invite sent %(user)s. They have already logged in and should reset their password."
                    )
                    % {"user": user},
                )

    invite_user_action.short_description = _("Invite selected users")
