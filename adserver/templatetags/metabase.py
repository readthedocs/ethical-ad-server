"""Custom template tags for metabase embedding."""
import logging
import time

import jwt
from django import template
from django.conf import settings
from django.template.loader import render_to_string


log = logging.getLogger(__name__)  # noqa
register = template.Library()


@register.simple_tag
def metabase_question_embed(question_id, **kwargs):
    """
    Embed a question (a graph in an iframe) from metabase.

    https://www.metabase.com/learn/embedding/embedding-charts-and-dashboards#an-example-using-django
    """
    if not settings.METABASE_SECRET_KEY:
        log.warning("Metabase Secret Key is not set - Graphs won't render")
        return None

    payload = {
        "resource": {"question": question_id},
        "params": kwargs,
        "exp": round(time.time()) + (60 * 10),
    }
    log.debug(payload)
    token = jwt.encode(payload, settings.METABASE_SECRET_KEY, algorithm="HS256")
    iframe_url = (
        settings.METABASE_SITE_URL + "/embed/question/" + token + "#bordered=true"
    )

    return render_to_string(
        "adserver/metabase/question-iframe.html", {"iframe_url": iframe_url}
    )
