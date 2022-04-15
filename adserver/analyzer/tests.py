from django.core.exceptions import ValidationError
from django.test import TestCase
from django_dynamic_fixture import get

from ..models import Publisher
from .models import AnalyzedUrl
from .utils import normalize_url
from .validators import KeywordsValidator


class TestValidators(TestCase):
    def test_keywords_validator(self):
        validator = KeywordsValidator(message="Test Message")

        # Ok
        validator([])
        validator(["django", "python"])
        validator(["ruby", "rails", "framework", "web", "http"])

        # Raise Errors
        self.assertRaises(ValidationError, validator, {})
        self.assertRaises(ValidationError, validator, "Not-List")
        self.assertRaises(
            ValidationError,
            validator,
            ["Upper", "Case"],
        )


class TestUtils(TestCase):
    def test_normalize_url(self):
        self.assertEqual(
            normalize_url("https://example.com/path"), "https://example.com/path"
        )
        self.assertEqual(
            normalize_url("https://example.com/path?myparam=myval"),
            "https://example.com/path?myparam=myval",
        )
        self.assertEqual(
            normalize_url("https://example.com/#fragment"),
            "https://example.com/#fragment",
        )

        # Test the ignored query params
        self.assertEqual(
            normalize_url("https://example.com/path?q=myval"),
            "https://example.com/path",
        )
        self.assertEqual(
            normalize_url("https://example.com/path?q=myval&myparam=saved"),
            "https://example.com/path?myparam=saved",
        )


class TestModels(TestCase):
    def setUp(self):
        self.publisher = get(Publisher)
        self.analyzed_url = AnalyzedUrl.objects.create(
            url="https://example.com",
            publisher=self.publisher,
            keywords=["python", "django"],
        )

    def test_str(self):
        self.assertEqual(
            str(self.analyzed_url), "['python', 'django'] on https://example.com"
        )

    def test_validation(self):
        self.analyzed_url.keywords = ["Python", "Django"]
        with self.assertRaises(ValidationError):
            self.analyzed_url.save()
