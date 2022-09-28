"""Spacy-based topic classifier that uses our trained model and gives a likelihood that text is about our topics."""
import logging

import langdetect

from .textacynlp import TextacyAnalyzerBackend


log = logging.getLogger(__name__)  # noqa


class EthicalAdsTopicsBackend(TextacyAnalyzerBackend):

    """A model that uses our own custom dataset behind the scenes."""

    # Name of the model package
    # A Python package of this name will be imported and IOError thrown if not present
    MODEL_NAME = "en_ethicalads_topics"

    # Below this body/text length, the model is unreliable
    # Return blank results lower than this length (~100 words)
    MIN_TEXT_LENGTH = 500

    # Threshold on the model
    MODEL_THRESHOLD = 0.4

    def skip_classification(self, text):
        """Return True if classification should be skipped."""
        if len(text) < self.MIN_TEXT_LENGTH:
            log.debug("Skipping classification. Too short.")
            return True

        if langdetect.detect(text) != "en":
            log.debug("Skipping classification due to non-English")
            return True

        return False

    def analyze_text(self, text):
        """Analyze text and return major topics (topics we are interested in) that the text is about."""
        if self.skip_classification(text):
            return []

        output = self.pretrained_model(text)
        return [k for k, v in output.cats.items() if v > self.MODEL_THRESHOLD]
