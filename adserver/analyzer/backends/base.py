"""Base class for all topic/keyword analyzers."""

import logging

import requests
import urllib3
from bs4 import BeautifulSoup
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
            return requests.get(self.url, **kwargs)
        except (requests.exceptions.RequestException, urllib3.exceptions.HTTPError):
            log.info("Error analyzing URL: %s", self.url, exc_info=True)

        return None

    def preprocess_text(self, text):
        return text.replace("\n", " ")[: self.MAX_INPUT_LENGTH]

    def get_content(self, resp):
        soup = BeautifulSoup(resp.content, features="html.parser")

        for selector in self.REMOVE_CONTENT_SELECTORS:
            for nodes in soup.select(selector):
                nodes.decompose()

        for selector in self.MAIN_CONTENT_SELECTORS:
            results = soup.select(selector, limit=1)
            # If no results, go to the next selector
            # If results are found, use these and stop looking at the selectors
            if results:
                return self.preprocess_text(results[0].get_text())

        return ""

    def analyze(self, resp):
        """
        Parse response for keywords.

        :returns list: a list of keywords or `None` if the URL doesn't respond.
        """

        if resp and resp.ok:
            return self.analyze_response(resp)

        if not resp:
            log.debug("Failed to connect. Url=%s", self.url)
        else:
            log.debug(
                "Failed to connect. Url=%s, Status=%s", self.url, resp.status_code
            )

        # A failed request results in `None`.
        return None

    def embedding(self, resp):
        """
        Parse the response for embeddings.

        :returns vector: A 384-dimensional vector or `None` if the URL doesn't respond.
        """

        if resp and resp.ok:
            return self.embed_response(resp)

        if not resp:
            log.debug("Failed to connect. Url=%s", self.url)
        else:
            log.debug(
                "Failed to connect. Url=%s, Status=%s", self.url, resp.status_code
            )

        return None

    def analyze_response(self, resp):
        """
        Analyze an HTTP resp and return keywords/topics for the URL.

        This will only be passed a successful resp (20x).
        All responses should return a list of keywords even if that list is empty.

        This needs to be defined by subclasses.
        """
        raise NotImplementedError("Subclasses should define this.")

    def embed_response(self, resp):
        """
        Analyze an HTTP response and return an embedding for the URL.

        This will only be passed a successful response (20x).
        All responses should return a vector even if that list is empty.
        """
        log.warning("No embedding configured for %s", self.__class__.__name__)
        return []


class BaseTrafilaturaBackend(BaseAnalyzerBackend):
    """Use Trafilatura's fetch backend instead of requests."""

    def fetch(self, **kwargs):
        """Performs a URL fetch on the analyzed URL."""
        import trafilatura  # noqa

        kwargs.setdefault("allow_redirects", False)
        kwargs.setdefault("timeout", 5)  # seconds

        # Options must be strings
        # https://trafilatura.readthedocs.io/en/latest/settings.html
        config = trafilatura.settings.use_config()

        # Technically, this is the download timeout, not the connect timeout
        # There's no connect timeout option
        config.set("DEFAULT", "DOWNLOAD_TIMEOUT", str(kwargs["timeout"]))
        config.set("DEFAULT", "USER_AGENTS", self.user_agent)
        if not kwargs["allow_redirects"]:
            config.set("DEFAULT", "MAX_REDIRECTS", "0")

        # Returns None on 40x response. Retries on 50x response a few times
        # https://trafilatura.readthedocs.io/en/latest/usage-python.html#choice-of-html-elements
        return trafilatura.fetch_url(self.url, config=config)

    def get_content(self, resp, *args):
        import trafilatura  # noqa

        if resp:
            self.metadata = trafilatura.extract_metadata(resp)

            # https://trafilatura.readthedocs.io/en/latest/usage-python.html#choice-of-html-elements
            result = trafilatura.extract(
                resp, include_comments=False, include_tables=False
            )

            return self.preprocess_text(result)
        return None

    def analyze(self, resp):
        """
        Parse response for keywords.

        :returns list: a list of keywords or `None` if the URL doesn't respond.
        """

        if resp:
            return self.analyze_response(resp)
        else:
            log.debug("Failed to connect. Url=%s", self.url)

        # A failed request results in `None`.
        return None

    def embedding(self, resp):
        """
        Parse the response for embeddings.

        :returns vector: A 384-dimensional vector or `None` if the URL doesn't respond.
        """

        if resp:
            return self.embed_response(resp)
        else:
            log.debug("Failed to connect. Url=%s", self.url)

        return None
