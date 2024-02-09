import logging
import os

from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer
from textacy import preprocessing

from ...models import Topic
from .base import BaseAnalyzerBackend

log = logging.getLogger(__name__)  # noqa


class SentenceTransformerAnalyzerBackend(BaseAnalyzerBackend):
    """
    Quick and dirty analyzer that uses the SentenceTransformer library
    """

    def preprocess_text(self, text):
        self.preprocessor = preprocessing.make_pipeline(
            preprocessing.normalize.unicode,
            preprocessing.remove.punctuation,
            preprocessing.normalize.whitespace,
        )
        return self.preprocessor(text).lower()[: self.MAX_INPUT_LENGTH]

    def analyze_response(self, resp):
        return []

    def embed_response(self, resp) -> list:
        """Analyze an HTTP response and return a list of keywords/topics for the URL."""
        model = SentenceTransformer(
            "multi-qa-MiniLM-L6-cos-v1",
            cache_folder=os.getenv(
                "SENTENCE_TRANSFORMERS_HOME", "/tmp/sentence_transformers"
            ),
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
