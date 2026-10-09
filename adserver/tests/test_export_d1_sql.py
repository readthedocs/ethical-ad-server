import datetime
import sqlite3
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from django_dynamic_fixture import get

from ..constants import PAID_CAMPAIGN
from ..models import AdType
from ..models import Advertisement
from ..models import Advertiser
from ..models import Campaign
from ..models import Flight
from ..models import Publisher
from ..utils import get_ad_day


if "adserver.analyzer" in settings.INSTALLED_APPS:
    from ..analyzer.models import AnalyzedUrl
else:
    AnalyzedUrl = None


class ExportD1SqlTestCase(TestCase):
    def setUp(self):
        self.publisher_active = get(
            Publisher,
            name="Active Publisher",
            slug="active-pub",
            disabled=False,
            default_keywords="python,django",
        )
        self.publisher_disabled = get(
            Publisher,
            name="Disabled Publisher",
            slug="disabled-pub",
            disabled=True,
        )

        if AnalyzedUrl is not None:
            self.url_active_1 = AnalyzedUrl.objects.create(
                publisher=self.publisher_active,
                url="https://example.com/active-url-1",
                domain="example.com",
                keywords=["python", "django"],
                last_analyzed_date=timezone.now(),
            )
            self.url_active_2 = AnalyzedUrl.objects.create(
                publisher=self.publisher_active,
                url="https://example.com/active-url-2",
                domain="example.com",
                keywords=["flask"],
                last_analyzed_date=timezone.now(),
            )
            self.url_disabled = AnalyzedUrl.objects.create(
                publisher=self.publisher_disabled,
                url="https://example.com/disabled-url",
                domain="example.com",
                keywords=["python"],
                last_analyzed_date=timezone.now(),
            )
            self.url_no_keywords = AnalyzedUrl.objects.create(
                publisher=self.publisher_active,
                url="https://example.com/no-keywords",
                domain="example.com",
                keywords=None,
                last_analyzed_date=timezone.now(),
            )
            self.url_not_analyzed = AnalyzedUrl.objects.create(
                publisher=self.publisher_active,
                url="https://example.com/not-analyzed",
                domain="example.com",
                keywords=["python"],
                last_analyzed_date=None,
            )

        self.advertiser = get(Advertiser, name="Test Advertiser")
        self.campaign = get(
            Campaign,
            name="Test Campaign",
            slug="test-campaign",
            advertiser=self.advertiser,
            campaign_type=PAID_CAMPAIGN,
        )

        self.ad_type = get(AdType, name="Sidebar", slug="readthedocs-sidebar")

        # Active flight (live=True, start_date <= today, has live ad)
        self.flight_active = get(
            Flight,
            name="Active Flight",
            slug="active-flight",
            live=True,
            campaign=self.campaign,
            start_date=get_ad_day().date() - datetime.timedelta(days=1),
            priority_multiplier=10,
            targeting_parameters={
                "include_countries": ["US", "CA"],
                "include_topics": ["python"],
            },
        )
        self.ad_active = get(
            Advertisement,
            name="Active Ad",
            slug="active-ad",
            link="https://example.com/active",
            live=True,
            flight=self.flight_active,
            headline="Headline Active",
            cta="Click Now",
            content="Body Active Content",
        )
        self.ad_active.ad_types.add(self.ad_type)

        # Inactive flight (live=False)
        self.flight_inactive = get(
            Flight,
            name="Inactive Flight",
            slug="inactive-flight",
            live=False,
            campaign=self.campaign,
            start_date=get_ad_day().date() - datetime.timedelta(days=1),
        )
        self.ad_inactive_flight = get(
            Advertisement,
            name="Inactive Flight Ad",
            slug="inactive-flight-ad",
            link="https://example.com/inactive",
            live=True,
            flight=self.flight_inactive,
        )
        self.ad_inactive_flight.ad_types.add(self.ad_type)

    def test_export_d1_sql_output(self):
        out = StringIO()
        call_command("export_d1_sql", stdout=out)
        sql_content = out.getvalue()

        # Check publisher output
        self.assertIn("'active-pub'", sql_content)
        self.assertNotIn("'disabled-pub'", sql_content)

        # Check campaign output
        self.assertIn("'test-campaign'", sql_content)

        # Check ad_type output
        self.assertIn("'readthedocs-sidebar'", sql_content)

        # Check flight output
        self.assertIn("'active-flight'", sql_content)
        self.assertNotIn("'inactive-flight'", sql_content)

        # Check advertisement output
        self.assertIn("'active-ad'", sql_content)
        self.assertNotIn("'inactive-flight-ad'", sql_content)

        # Check advertisement_ad_types output
        self.assertIn("INSERT OR REPLACE INTO advertisement_ad_types", sql_content)

        # Check AnalyzedUrls output
        self.assertIn("https://example.com/active-url-1", sql_content)
        self.assertIn("https://example.com/active-url-2", sql_content)
        self.assertNotIn("https://example.com/disabled-url", sql_content)
        self.assertNotIn("https://example.com/no-keywords", sql_content)
        self.assertNotIn("https://example.com/not-analyzed", sql_content)

    def test_export_d1_sql_max_urls(self):
        out = StringIO()
        call_command("export_d1_sql", max_urls=1, stdout=out)
        sql_content = out.getvalue()

        self.assertIn("-- URLs (1)", sql_content)
        self.assertEqual(sql_content.count("INSERT OR REPLACE INTO urls"), 1)

    def test_export_d1_sql_batching(self):
        """Test that URLs are batched at 100 per INSERT statement."""
        if AnalyzedUrl is None:
            self.skipTest("Analyzer not setup")

        # Create 105 more URLs to test batch splitting (total 107 active URLs)
        AnalyzedUrl.objects.bulk_create(
            [
                AnalyzedUrl(
                    publisher=self.publisher_active,
                    url=f"https://example.com/batch-test-{i}",
                    domain="example.com",
                    keywords=["batch"],
                    last_analyzed_date=timezone.now(),
                )
                for i in range(105)
            ]
        )

        out = StringIO()
        call_command("export_d1_sql", stdout=out)
        sql_content = out.getvalue()

        # 2 existing active URLs + 105 new = 107 URLs
        # 107 URLs batched at 100/statement should produce exactly 2 INSERT statements for urls
        self.assertEqual(sql_content.count("INSERT OR REPLACE INTO urls"), 2)

    def test_sqlite_execution(self):
        """Test executing generated SQL against worker schema.sql in SQLite."""
        schema_path = Path(
            "/home/david/ReadTheDocs/ethicalads-decision-worker/schema.sql"
        )
        if not schema_path.exists():
            self.skipTest("schema.sql not found at expected location")

        schema_sql = schema_path.read_text(encoding="utf-8")

        out = StringIO()
        call_command("export_d1_sql", stdout=out)
        sql_content = out.getvalue()

        conn = sqlite3.connect(":memory:")
        conn.executescript(schema_sql)
        conn.executescript(sql_content)

        # Verify inserted data in SQLite
        cursor = conn.cursor()
        cursor.execute("SELECT slug, disabled FROM publishers")
        pubs = cursor.fetchall()
        self.assertEqual(len(pubs), 1)
        self.assertEqual(pubs[0][0], "active-pub")
        self.assertEqual(pubs[0][1], 0)

        cursor.execute("SELECT slug, name FROM ad_types")
        ad_types = cursor.fetchall()
        self.assertEqual(len(ad_types), 1)
        self.assertEqual(ad_types[0][0], "readthedocs-sidebar")

        cursor.execute("SELECT slug, advertiser_name, logo FROM campaigns")
        camps = cursor.fetchall()
        self.assertEqual(len(camps), 1)
        self.assertEqual(camps[0][0], "test-campaign")

        cursor.execute(
            "SELECT slug, campaign_slug, target_geos, target_topics, logo, pacing_interval, weighted_clicks_needed_this_interval FROM flights"
        )
        flights = cursor.fetchall()
        self.assertEqual(len(flights), 1)
        self.assertEqual(flights[0][0], "active-flight")
        self.assertEqual(flights[0][1], "test-campaign")
        self.assertIn("CA US", flights[0][2])
        self.assertIn("python", flights[0][3])
        self.assertEqual(flights[0][5], self.flight_active.pacing_interval)
        self.assertIsInstance(flights[0][6], (int, float))

        cursor.execute(
            "SELECT slug, flight_slug, headline, cta, image FROM advertisements"
        )
        ads = cursor.fetchall()
        self.assertEqual(len(ads), 1)
        self.assertEqual(ads[0][0], "active-ad")
        self.assertEqual(ads[0][1], "active-flight")
        self.assertEqual(ads[0][2], "Headline Active")
        self.assertEqual(ads[0][3], "Click Now")

        cursor.execute("SELECT ad_id, ad_type_slug FROM advertisement_ad_types")
        ad_ad_types = cursor.fetchall()
        self.assertEqual(len(ad_ad_types), 1)
        self.assertEqual(ad_ad_types[0][0], self.ad_active.id)
        self.assertEqual(ad_ad_types[0][1], "readthedocs-sidebar")

        cursor.execute("SELECT url_hash, url, domain, tags FROM urls")
        urls = cursor.fetchall()
        self.assertEqual(len(urls), 2)
        urls_by_url = {u[1]: u for u in urls}
        self.assertIn("https://example.com/active-url-1", urls_by_url)
        self.assertEqual(
            urls_by_url["https://example.com/active-url-1"][3], "python django"
        )
        self.assertIn("https://example.com/active-url-2", urls_by_url)
        self.assertEqual(urls_by_url["https://example.com/active-url-2"][3], "flask")

        conn.close()

    def test_export_to_file(self, tmp_path=None):
        out_file = self.id() + "_test.sql"
        try:
            call_command("export_d1_sql", output=out_file)
            with open(out_file, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("'active-pub'", content)
            self.assertIn("'active-flight'", content)
        finally:
            path = Path(out_file)
            if path.exists():
                path.unlink()
