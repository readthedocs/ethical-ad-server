"""Custom template tags for metabase embedding."""

import logging
import time
from datetime import date
from datetime import datetime

import jwt
from django import template
from django.conf import settings
from django.template.loader import render_to_string


log = logging.getLogger(__name__)  # noqa
register = template.Library()


def serialize_params(params):
    """Formats some metabase parameters so they can be JSON serialized."""
    # These parameters must be JSON serializable to be signed
    # Notably, dates aren't serializable by default
    serializable_params = {}
    for k, val in params.items():
        if isinstance(val, (date, datetime)):
            serializable_params[k] = str(val)
        else:
            serializable_params[k] = val

    return serializable_params


@register.simple_tag
def metabase_question_embed(question_id, **kwargs):
    """
    Embed a question (a graph in an iframe) from metabase.

    https://www.metabase.com/learn/embedding/embedding-charts-and-dashboards#an-example-using-django
    """
    if not question_id:
        return None

    if not settings.METABASE_SECRET_KEY:
        log.warning("Metabase Secret Key is not set - Graphs won't render")
        return None

    payload = {
        "resource": {"question": question_id},
        "params": serialize_params(kwargs),
        "exp": round(time.time()) + (60 * 10),  # cache expiration
    }

    token = jwt.encode(payload, settings.METABASE_SECRET_KEY, algorithm="HS256")
    iframe_url = (
        settings.METABASE_SITE_URL
        + "/embed/question/"
        + token
        + "#bordered=true&titled=false"
    )

    return render_to_string(
        "adserver/metabase/question-iframe.html", {"iframe_url": iframe_url}
    )


@register.simple_tag
def metabase_dashboard_embed(dashboard_id, **kwargs):
    """Embeds a dashboard instead of a question."""
    if not dashboard_id:
        return None

    if not settings.METABASE_SECRET_KEY:
        log.warning("Metabase Secret Key is not set - Graphs won't render")
        return None

    payload = {
        "resource": {"dashboard": dashboard_id},
        "params": serialize_params(kwargs),
        "exp": round(time.time()) + (60 * 10),  # cache expiration
    }

    token = jwt.encode(payload, settings.METABASE_SECRET_KEY, algorithm="HS256")
    iframe_url = (
        settings.METABASE_SITE_URL
        + "/embed/dashboard/"
        + token
        + "#bordered=true&titled=false"
    )

    return render_to_string(
        "adserver/metabase/dashboard-iframe.html", {"iframe_url": iframe_url}
    )
