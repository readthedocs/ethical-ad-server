"""Base class for all topic/keyword analyzers."""
import logging

import requests
import urllib3
from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site


log = logging.getLogger(__name__)  # noqa


class BaseAnalyzerBackend:

    """Base class that all analyzers should extend."""

    # CSS selectors to select the "main" content of the page
    # The first of these to match anything is used
    MAIN_CONTENT_SELECTORS = (
        "[role='main']",
        "main",
        "body",
    )

    # CSS selectors of content that should be ignored for the purpose of analysis
    REMOVE_CONTENT_SELECTORS = (
        "[role=navigation]",
        "[role=search]",
        ".headerlink",
        "nav",
        "footer",
        "div.header",
        # Remove toctrees from Sphinx
        "div.toctree-wrapper",
        # Remove class and function definitions from Sphinx
        # but leave the actual docstrings/explanations
        "dl.class dt",
        # Django Packages specific
        "#myrotatingnav",
    )

    # Some models have limits but beyond ~100k characters
    # we probably aren't learning more
    MAX_INPUT_LENGTH = 100_000

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
            self.resp = requests.get(self.url, **kwargs)
            return self.resp
        except (requests.exceptions.RequestException, urllib3.exceptions.HTTPError):
            log.info("Error analyzing URL: %s", self.url, exc_info=True)

        return None

    def analyze(self):
        """
        Fetch the response and parse it for keywords.

        :returns list: a list of keywords or `None` if the URL doesn't respond.
        """
        self.fetch()

        if self.resp and self.resp.ok:
            return self.analyze_response(self.resp)

        if not self.resp:
            log.debug("Failed to connect. Url=%s", self.url)
        else:
            log.debug(
                "Failed to connect. Url=%s, Status=%s", self.url, self.resp.status_code
            )

        # A failed request results in `None`.
        return None

    def embedding(self):
        """
        Parse the response for embeddings.

        :returns vector: A 384-dimensional vector or `None` if the URL doesn't respond.
        """

        if self.resp and self.resp.ok:
            return self.embed_response(self.resp)

        if not self.resp:
            log.debug("Failed to connect. Url=%s", self.url)
        else:
            log.debug(
                "Failed to connect. Url=%s, Status=%s", self.url, self.resp.status_code
            )

        return None

    def analyze_response(self, resp):
        """
        Analyze an HTTP response and return keywords/topics for the URL.

        This will only be passed a successful response (20x).
        All responses should return a list of keywords even if that list is empty.

        This needs to be defined by subclasses.
        """
        raise NotImplementedError("Subclasses should define this.")

    def embed_response(self, resp):
        """
        Analyze an HTTP response and return an embedding for the URL.

        This will only be passed a successful response (20x).
        All responses should return a vector even if that list is empty.

        This needs to be defined by subclasses.
        """
        raise NotImplementedError("Subclasses should define this.")
