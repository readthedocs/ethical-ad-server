"""Custom template tags for advertisements."""

import logging

from django import template
from django.utils.safestring import mark_safe


log = logging.getLogger(__name__)  # noqa
register = template.Library()


@register.simple_tag
def advertisement_preview(ad, ad_type=None):
    """Render an ad preview with the given ad type (or the first of that ads types)."""
    if not ad_type:
        ad_type = ad.ad_types.first()

    return mark_safe(ad.render_ad(ad_type, preview=True))


@register.simple_tag
def advertiser_manager_role(user, advertiser):
    """
    Returns True if the user has manager or higher role on this advertiser and False otherwise.

    Return True for staff.
    """
    return user.is_staff or user.has_advertiser_manager_permission(advertiser)


@register.simple_tag
def advertiser_admin_role(user, advertiser):
    """
    Returns True if the user has admin role on this advertiser and False otherwise.

    Return True for staff.
    """
    return user.is_staff or user.has_advertiser_admin_permission(advertiser)


@register.simple_tag
def publisher_manager_role(user, publisher):
    """
    Returns True if the user has manager or higher role on this publisher and False otherwise.

    Return True for staff.
    """
    return user.is_staff or user.has_publisher_manager_permission(publisher)


@register.simple_tag
def publisher_admin_role(user, publisher):
    """
    Returns True if the user has admin role on this publisher and False otherwise.

    Return True for staff.
    """
    return user.is_staff or user.has_publisher_admin_permission(publisher)
