"""Naive keyword analyzer that is simply based on keyword counts."""
import collections

from bs4 import BeautifulSoup

from ...models import Topic
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

    MAX_WORDS_ANALYZED = 1000
    MAX_KEYWORDS = 3
    MIN_KEYWORD_OCCURRENCES = 2

    # Some models have limits but beyond ~100k characters
    # we probably aren't learning more
    MAX_INPUT_LENGTH = 100_000

    def __init__(self, url, **kwargs):
        """Overrides to get the keyword corpus."""
        super().__init__(url, **kwargs)

        self.topics = Topic.load_from_cache()
        self.keyword_corpus = []

        for topic in self.topics:
            for kw in self.topics[topic]:
                self.keyword_corpus.append(kw)

    def analyze_response(self, resp):
        """Analyze an HTTP response and return a list of keywords/topics for the URL."""
        keywords = []

        soup = BeautifulSoup(resp.content, features="html.parser")

        for selector in self.REMOVE_CONTENT_SELECTORS:
            for nodes in soup.select(selector):
                nodes.decompose()

        for selector in self.MAIN_CONTENT_SELECTORS:
            results = soup.select(selector, limit=1)

            # If no results, go to the next selector
            # If results are found, use these and stop looking at the selectors
            if results:
                text = self.preprocess_text(results[0].get_text())
                keywords = self.analyze_text(text)
                break

        return keywords

    def preprocess_text(self, text):
        return text.replace("\n", " ")[: self.MAX_INPUT_LENGTH]

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
