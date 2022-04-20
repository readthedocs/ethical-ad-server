"""Naive keyword analyzer that is simply based on keyword counts."""
import collections

from bs4 import BeautifulSoup

from ... import regiontopics as topics
from .base import BaseAnalyzerBackend


class NaiveKeywordAnalyzerBackend(BaseAnalyzerBackend):

    """
    A very naive keyword analyzer.

    This mimics the results of our ad client.
    """

    # CSS selectors to select the "main" content of the page
    # The first of these to match anything is used
    MAIN_CONTENT_SELECTORS = (
        "[role='main']",
        "main",
        "body",
    )

    MAX_WORDS_ANALYZED = 1000
    MAX_KEYWORDS = 3
    MIN_KEYWORD_OCCURRENCES = 2

    def __init__(self, url, **kwargs):
        """Overrides to get the keyword corpus."""
        super().__init__(url, **kwargs)

        self.keyword_corpus = (
            topics.data_science
            + topics.backend_web
            + topics.frontend_web
            + topics.security_privacy
            + topics.devops
            + topics.python
            + topics.game_dev
            + topics.blockchain
            + topics.techwriting
        )

    def analyze_response(self, resp):
        """Analyze an HTTP response and return a list of keywords/topics for the URL."""
        keywords = []

        soup = BeautifulSoup(resp.content, features="html.parser")

        for selector in self.MAIN_CONTENT_SELECTORS:
            results = soup.select(selector, limit=1)

            # If no results, go to the next selector
            # If results are found, use these and stop looking at the selectors
            if results:
                text = results[0].get_text().replace("\n", " ")
                keywords = self.analyze_text(text)
                break

        return keywords

    def analyze_text(self, text):
        """Analyze a large string of text for keyword extraction."""
        # Differs from string.punctuation in that the hyphen is missing
        punctuation = r"""!"#$%&'()*+,./:;<=>?@[\]^_`{|}~"""

        word_counter = collections.Counter()

        for index, word in enumerate(text.split()):
            if index > self.MAX_WORDS_ANALYZED:
                break

            # Remove punctuation and make it lowercase
            word = word.translate(str.maketrans("", "", punctuation)).lower()

            if word in self.keyword_corpus:
                word_counter[word] += 1

        # Remove items with fewer than MIN_KEYWORD_OCCURRENCES
        word_counter = collections.Counter(
            {k: v for k, v in word_counter.items() if v >= self.MIN_KEYWORD_OCCURRENCES}
        )

        # Return the top MAX_KEYWORDS
        return [kw for kw, _ in word_counter.most_common(self.MAX_KEYWORDS)]
