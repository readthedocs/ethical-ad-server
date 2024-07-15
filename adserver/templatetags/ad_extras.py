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
