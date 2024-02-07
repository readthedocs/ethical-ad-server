import logging
import os

from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer

from ...models import Topic
from .textacynlp import TextacyAnalyzerBackend

log = logging.getLogger(__name__)  # noqa


class SentenceTransformerAnalyzerBackend(TextacyAnalyzerBackend):
    """
    Quick and dirty analyzer that uses the SentenceTransformer library

    Quick start testing:

    ```
    ADSERVER_ANALYZER_BACKEND=adserver.analyzer.backends.SentenceTransformerAnalyzerBackend ./manage.py shell_plus

    from adserver.analyzer.tasks import analyze_url

    analyze_url('https://ericholscher.com/blog/2014/feb/11/sphinx-isnt-just-for-python/', publisher_slug='ethicaladsio', force=True)
    ```"""

    def __init__(self, url, **kwargs):
        """Overrides to get the keyword corpus."""
        super().__init__(url, **kwargs)

        self.topics = Topic.load_from_cache()
        self.keyword_corpus = []

        for topic in self.topics:
            for kw in self.topics[topic]:
                self.keyword_corpus.append(kw)

    def analyze_response(self, resp):
        return []

    def embed_response(self, resp) -> list:
        """Analyze an HTTP response and return a list of keywords/topics for the URL."""
        model = SentenceTransformer(
            "multi-qa-MiniLM-L6-cos-v1",
            cache_folder=os.getenv("SENTENCE_TRANSFORMERS_HOME", "/model/"),
        )

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
                log.info("Embedding text: %s", text[:100])
                embedding = model.encode(text)

                return embedding.tolist()

        return None
