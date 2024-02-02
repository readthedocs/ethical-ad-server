import logging

from sentence_transformers import SentenceTransformer

from ...models import Topic
from .base import BaseAnalyzerBackend

log = logging.getLogger(__name__)  # noqa


class SentenceTransformerAnalyzerBackend(BaseAnalyzerBackend):
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
        keywords = []

        model = SentenceTransformer("multi-qa-MiniLM-L6-cos-v1")
        embedding = model.encode(str(resp.content))

        return embedding.tolist()
