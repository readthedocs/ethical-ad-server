import datetime

import pytest
import requests
import responses
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from django_dynamic_fixture import get

from . import tasks
from ..models import Offer
from ..models import Publisher
from ..tests.common import BaseAdModelsTestCase
from .backends import EthicalAdsTopicsBackend
from .backends import NaiveKeywordAnalyzerBackend
from .backends import TextacyAnalyzerBackend
from .models import AnalyzedUrl
from .utils import get_url_analyzer_backend
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

    def test_get_analyzer_class(self):
        self.assertEqual(
            get_url_analyzer_backend(),
            TextacyAnalyzerBackend,
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


class TestNaiveAnalyzer(TestCase):
    def setUp(self):
        self.url = "https://example.com"
        self.analyzer = NaiveKeywordAnalyzerBackend(self.url)

    @responses.activate
    def test_analyzer_success(self):
        responses.add(
            responses.GET,
            self.url,
            body="""
            <html>
            <head>
            </head>
            <body>
                <!-- Ignored: blockchain blockchain blockchain -->

                <!-- Nav is also ignored since there's a "main" -->
                <nav>datascience, datascience, datascience</nav>

                <!-- Only this should be used -->
                <main>
                <p>devops, DevOps, DevOps, backend, frontend, frontend</p>
                </main>
            </body>
            </html>
            """,
        )
        self.assertEqual(
            self.analyzer.analyze(),
            ["devops", "frontend"],  # Backend doesn't appear enough
        )

    @responses.activate
    def test_analyzer_fail(self):
        responses.add(
            responses.GET,
            self.url,
            status=404,
        )
        self.assertIsNone(self.analyzer.analyze())

        responses.reset()

        responses.add(
            responses.GET,
            self.url,
            status=500,
        )
        self.assertIsNone(self.analyzer.analyze())

        responses.reset()

        responses.add(
            responses.GET,
            self.url,
            body=requests.exceptions.ConnectTimeout(),
        )
        self.assertIsNone(self.analyzer.analyze())


class TestTextacyAnalyzerBackend(TestCase):
    def setUp(self):
        self.url = "https://example.com"
        self.analyzer = TextacyAnalyzerBackend(self.url)

    @responses.activate
    def test_analyzer_success(self):
        responses.add(
            responses.GET,
            self.url,
            body="""
            <html>
            <head>
            </head>
            <body>
                <!-- Ignored: blockchain blockchain blockchain -->

                <!-- Nav is also ignored since there's a "main" -->
                <nav>data science, data science, data science</nav>

                <!-- Only this should be used -->
                <main>
                <p>Data science and machine learning are important</p>
                <p>With Data science and machine learning you can analyze text</p>
                <p>DevOps is less critical here</p>
                </main>
            </body>
            </html>
            """,
        )
        self.assertEqual(
            self.analyzer.analyze(),
            ["data-science", "machine-learning", "devops"],
        )

    @responses.activate
    def test_analyzer_fail(self):
        responses.add(
            responses.GET,
            self.url,
            status=404,
        )
        self.assertIsNone(self.analyzer.analyze())

        responses.reset()

        responses.add(
            responses.GET,
            self.url,
            status=500,
        )
        self.assertIsNone(self.analyzer.analyze())

        responses.reset()

        responses.add(
            responses.GET,
            self.url,
            body=requests.exceptions.ConnectTimeout(),
        )
        self.assertIsNone(self.analyzer.analyze())


class TestEthicalAdsTopicsBackend(TestCase):
    def setUp(self):
        self.url = "https://example.com"

        try:
            self.analyzer = EthicalAdsTopicsBackend(self.url)
        except IOError:
            pytest.skip()

    @responses.activate
    def test_analyzer_not_long_enough(self):
        responses.add(
            responses.GET,
            self.url,
            body="""
                <html>
                <head>
                </head>
                <body>
                    <main>
                    <p>Not long enough</p>
                    </main>
                </body>
                </html>
                """,
        )
        self.assertEqual(
            self.analyzer.analyze(),
            [],
        )


class TestTasks(BaseAdModelsTestCase):
    def setUp(self):
        super().setUp()

        self.url = "https://example.com"
        self.analyzed_url = AnalyzedUrl.objects.create(
            url=self.url,
            publisher=self.publisher,
            keywords=["python", "django"],
            visits_since_last_analyzed=10,
            last_analyzed_date=timezone.now() - datetime.timedelta(days=20),
        )

        self.campaign.campaign_type = "paid"
        self.campaign.save()

    @responses.activate
    def test_analyze_url(self):
        responses.add(
            responses.GET,
            self.url,
            body="""
                <html>
                <head>
                </head>
                <body>
                    Not used keywords
                    Backend Backend Backend
                </body>
                </html>
                """,
        )
        tasks.analyze_url(self.url, self.publisher.slug)
        self.analyzed_url.refresh_from_db()

        self.assertEqual(self.analyzed_url.keywords, ["backend"])
        self.assertEqual(self.analyzed_url.visits_since_last_analyzed, 0)

    def test_daily_visited_urls_aggregation(self):
        url2 = "https://example.com/path/"
        yesterday = timezone.now() - datetime.timedelta(days=1)

        # Ad a few offers for a page
        get(
            Offer,
            publisher=self.publisher,
            url=url2,
            advertisement=self.ad1,
            div_id="p1",
            viewed=True,
            date=yesterday,
        )
        get(
            Offer,
            publisher=self.publisher,
            url=url2,
            advertisement=self.ad1,
            div_id="p1",
            viewed=True,
            date=yesterday,
        )
        get(
            Offer,
            publisher=self.publisher,
            url=url2,
            advertisement=self.ad1,
            div_id="p1",
            viewed=False,  # NOTE!! Not viewed!
            date=yesterday,
        )

        tasks.daily_visited_urls_aggregation()

        analyzed_url = AnalyzedUrl.objects.filter(
            url=url2, publisher=self.publisher
        ).first()
        self.assertIsNotNone(analyzed_url)
        self.assertEqual(analyzed_url.visits_since_last_analyzed, 2)

        # Add another view and make sure the aggregation adds it correctly
        get(
            Offer,
            publisher=self.publisher,
            url=url2,
            advertisement=self.ad1,
            div_id="p1",
            viewed=True,
            date=timezone.now(),
        )
        tasks.daily_visited_urls_aggregation(timezone.now().today())
        analyzed_url = AnalyzedUrl.objects.filter(
            url=url2, publisher=self.publisher
        ).first()
        self.assertIsNotNone(analyzed_url)
        self.assertEqual(analyzed_url.visits_since_last_analyzed, 3)

    @responses.activate
    def test_daily_analyze_urls(self):
        tasks.daily_analyze_urls()
        self.analyzed_url.refresh_from_db()

        # No URL analyzed since it hasn't been visited "enough"
        self.assertEqual(self.analyzed_url.visits_since_last_analyzed, 10)

        # Setup a response
        responses.add(
            responses.GET,
            self.url,
            body="""<html><body>python python python Python Python</body></html>""",
        )

        # Set the URL for re-analysis
        self.analyzed_url.visits_since_last_analyzed = 100
        self.analyzed_url.save()

        tasks.daily_analyze_urls()
        self.analyzed_url.refresh_from_db()

        # Analyzed URL has been updated
        self.assertEqual(self.analyzed_url.keywords, ["python"])
        self.assertEqual(self.analyzed_url.visits_since_last_analyzed, 0)
