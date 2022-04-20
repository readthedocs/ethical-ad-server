"""Base class for all topic/keyword analyzers."""
import logging

import requests
import urllib3
from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site


log = logging.getLogger(__name__)  # noqa


class BaseAnalyzerBackend:

    """Base class that all analyzers should extend."""

    def __init__(self, url, **kwargs):
        """Base constructor."""
        self.url = url

        site = get_current_site(request=None)
        self.user_agent = (
            f"EthicalAds Analyzer/{settings.ADSERVER_VERSION} <{site.domain}>"
        )

    def fetch(self, **kwargs):
        """Performs a URL fetch on the analyzed URL."""
        # Unless specifically following redirects, don't bother
        # Something is probably wrong if the request returns a redirect
        kwargs.setdefault("allow_redirects", False)
        kwargs.setdefault("timeout", 3)  # seconds
        kwargs.setdefault("headers", {"user-agent": self.user_agent})

        try:
            return requests.get(self.url, **kwargs)
        except (requests.exceptions.RequestException, urllib3.exceptions.HTTPError):
            log.info("Error analyzing URL: %s", self.url, exc_info=True)

        return None

    def analyze(self):
        """
        Fetch the response and parse it for keywords.

        :returns list: a list of keywords or `None` if the URL doesn't respond.
        """
        resp = self.fetch()

        if resp and resp.ok:
            return self.analyze_response(resp)

        # A failed request results in `None`.
        return None

    def analyze_response(self, resp):
        """
        Analyze an HTTP response and return keywords/topics for the URL.

        This will only be passed a successful response (20x).
        All responses should return a list of keywords even if that list is empty.

        This needs to be defined by subclasses
        """
        raise NotImplementedError("Subclasses should define this.")
