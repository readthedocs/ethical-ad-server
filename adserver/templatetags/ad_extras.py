"""Custom template tags for advertisements."""

from django import template
from django.utils.safestring import mark_safe


register = template.Library()


@register.simple_tag
def advertisement_preview(ad, ad_type=None):
    """Render an ad preview with the given ad type (or the first of that ads types)."""
    if not ad_type:
        ad_type = ad.ad_types.first()

    return mark_safe(ad.render_ad(ad_type, preview=True))


@register.simple_tag
def advertiser_role(user, advertiser):
    """
    Returns the users role in this advertiser or None if the user has no permissions.

    Staff status is not taken into account. Caches the result on the user so future calls
    don't involve a DB lookup.
    """
    if not hasattr(user, "_advertiser_roles"):
        user._advertiser_roles = {}

    if advertiser.pk in user._advertiser_roles:
        return user._advertiser_roles[advertiser.pk]

    membership = user.useradvertisermember_set.filter(
        advertiser=advertiser,
    ).first()

    role = None
    if membership:
        role = membership.role

    user._advertiser_roles[advertiser.pk] = role
    return role


@register.simple_tag
def publisher_role(user, publisher):
    """
    Returns the users role in this publisher or None if the user has no permissions.

    Staff status is not taken into account. Caches the result on the user so future calls
    don't involve a DB lookup.
    """
    if not hasattr(user, "_publisher_roles"):
        user._publisher_roles = {}

    if publisher.pk in user._publisher_roles:
        return user._publisher_roles[publisher.pk]

    membership = user.userpublishermember_set.filter(
        publisher=publisher,
    ).first()

    role = None
    if membership:
        role = membership.role

    user._publisher_roles[publisher.pk] = role
    return role
