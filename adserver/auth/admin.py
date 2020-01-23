"""Django admin configuration for the Ad Server authentication app."""
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):

    """Django admin configuration for users."""

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
