"""Django admin configuration for the Ad Server authentication app."""

from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "name",
        "is_active",
        "is_staff",
        "last_login",
        "created_date",
    )
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("email", "name")
