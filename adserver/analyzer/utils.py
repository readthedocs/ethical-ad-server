"""Helper utilities for the adserver analyzer."""
from urllib import parse as urlparse

from django.conf import settings
from django.utils.module_loading import import_string

from .constants import IGNORED_QUERY_PARAMS


def get_url_analyzer_backends():
    for backend in settings.ADSERVER_ANALYZER_BACKEND:
        if backend:
            yield import_string(backend)


def get_url_analyzer_backend():
    backends = list(get_url_analyzer_backends())
    if backends:
        return backends[0]

    return None


def normalize_url(url):
    """
    Normalize a URL.

    Currently, this means:
    - Removing ignored query paramters
    """
    parts = urlparse.urlparse(url)

    query_params = urlparse.parse_qs(parts.query, keep_blank_values=True)
    for param in IGNORED_QUERY_PARAMS:
        if param in query_params:
            query_params.pop(param)

    # The _replace method is a documented method even though it appears "private"
    parts = parts._replace(query=urlparse.urlencode(query_params, True))

    return urlparse.urlunparse(parts)
