"""Textacy/Spacy-based keyword analyzer that lemmatizes and uses textrank for keyphrase extraction."""
import collections
import logging

import textacy
from textacy import preprocessing

from .naive import NaiveKeywordAnalyzerBackend


log = logging.getLogger(__name__)  # noqa


class TextacyAnalyzerBackend(NaiveKeywordAnalyzerBackend):

    """
    An analyzer backend that uses textacy for lemmatization and keyword extraction.

    https://textacy.readthedocs.io/en/latest/quickstart.html
    """

    TOP_PHRASE_COUNT = 20

    # Minimum phrase length where each word isn't required to be in the output phrase
    MIN_PHRASE_LENGTH = 6

    def __init__(self, url, **kwargs):
        """Overrides to lemmatize keywords."""
        super().__init__(url, **kwargs)

        self.pretrained_model = textacy.load_spacy_lang(
            "en_core_web_md", disable=("parser",)
        )

        self.preprocessor = preprocessing.make_pipeline(
            preprocessing.normalize.unicode,
            preprocessing.remove.punctuation,
            preprocessing.normalize.whitespace,
        )

        # Maps lemmatized keywords back to the original keyword/phrase in our database
        self.lemmatized_to_original_map = {}

        # Reset the keywords
        self.keyword_corpus = []

        # Build up the lemmatized keywords
        for topic in self.topics:
            for keyword in self.topics[topic]:
                terms_doc = textacy.make_spacy_doc(
                    self.preprocessor(keyword).lower(), lang=self.pretrained_model
                )
                words = list(
                    textacy.extract.utils.terms_to_strings(terms_doc, by="lemma")
                )
                phrase = " ".join(words)
                self.keyword_corpus.append(phrase)
                self.lemmatized_to_original_map[phrase] = keyword

    def preprocess_text(self, text):
        return self.preprocessor(text).lower()

    def analyze_text(self, text):
        """
        Analyze a large string of text for keyword extraction.

        One notable difference from the other backends is that the matching
        keywords/phrases should be in order of how used/present they are.
        """
        doc = textacy.make_spacy_doc(text, lang=self.pretrained_model)
        keyword_counter = collections.Counter()

        # Lemmatize the words/phrases to make sure we're always finding exactly what we're looking for
        # Bias toward the early part of the document
        for phrase, weight in textacy.extract.keyterms.textrank(
            doc, normalize="lemma", position_bias=True, topn=self.TOP_PHRASE_COUNT
        ):
            log.debug(f"Key phrase: {phrase}")
            # Check if the phrases we are interested in finding
            # appear in the keyterms as analyzed by textrank
            for keyphrase in self.keyword_corpus:
                if keyphrase in phrase:
                    # The keyphrase is present in the keyterms
                    # However, make sure those appear on word boundaries
                    # Or the word is long enough where that shouldn't matter
                    # (eg. avoid the "ai" in "email" problem)
                    keyphrase_set = set(keyphrase.split())
                    if any(
                        (
                            len(keyphrase) > self.MIN_PHRASE_LENGTH,
                            keyphrase_set
                            == keyphrase_set.intersection(set(phrase.split())),
                        )
                    ):
                        keyword_counter[keyphrase] += weight

        return [
            self.lemmatized_to_original_map[kw]
            for kw, _ in keyword_counter.most_common(self.MAX_KEYWORDS)
        ]
