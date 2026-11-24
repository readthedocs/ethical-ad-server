import datetime
import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import management
from django.db import models
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from django_dynamic_fixture import get

from ..constants import PAID_CAMPAIGN
from ..models import AdImpression
from ..models import AdType
from ..models import Advertisement
from ..models import Advertiser
from ..models import Campaign
from ..models import Click
from ..models import Flight
from ..models import Publisher
from ..utils import get_ad_day


if "adserver.analyzer" in settings.INSTALLED_APPS:
    from ..analyzer.models import AnalyzedUrl
else:
    AnalyzedUrl = None


User = get_user_model()


class TestImporterManagementCommand(TestCase):
    def setUp(self):
        base_path = os.path.abspath(os.path.dirname(__file__))
        dumpfile = os.path.join(base_path, "fixtures/import_dumpfile.json")
        out = io.StringIO()
        management.call_command("rtdimport", dumpfile, stdout=out)

    def test_import_counts(self):
        self.assertEqual(Publisher.objects.count(), 2)
        self.assertEqual(Advertisement.objects.count(), 2)
        self.assertEqual(Flight.objects.count(), 2)
        self.assertEqual(Campaign.objects.count(), 2)

        # House/Community ads create a single advertiser
        self.assertEqual(Advertiser.objects.count(), 1)

        self.assertEqual(Click.objects.count(), 2)

        # The 2 project impressions collapse into 1
        # since they are the same "publisher" and ad
        self.assertEqual(AdImpression.objects.count(), 3)

    def test_impression_values(self):
        readthedocs_publisher = Publisher.objects.get(slug="readthedocs")
        other_publisher = Publisher.objects.get(slug="readthedocs-pallets")

        # take the total and subtract the impressions from other publishers (150 - 40 - 30)
        self.assertEqual(
            AdImpression.objects.filter(
                advertisement_id=1, publisher=readthedocs_publisher
            ).aggregate(sum_views=models.Sum("views"))["sum_views"],
            80,
        )

        # 40 + 30
        self.assertEqual(
            AdImpression.objects.filter(
                advertisement_id=1, publisher=other_publisher
            ).aggregate(sum_views=models.Sum("views"))["sum_views"],
            70,
        )

        self.assertEqual(
            AdImpression.objects.filter(advertisement_id=1).aggregate(
                sum_views=models.Sum("views")
            )["sum_views"],
            150,
        )

    def test_flight_targeting(self):
        flight1 = Flight.objects.filter(slug="house-flight").first()
        self.assertIsNotNone(flight1)

        # exclude programming languages was removed
        self.assertDictEqual(flight1.targeting_parameters, {})

        flight2 = Flight.objects.filter(slug="house-flight-2").first()
        self.assertIsNotNone(flight2)
        self.assertDictEqual(
            flight2.targeting_parameters,
            {
                "include_keywords": ["python", "readthedocs-project-123"]
            },  # Order of the list isn't relevant
        )


class TestArchiveOffers(TestCase):
    def setUp(self):
        self.out = io.StringIO()
        self.err = io.StringIO()

    def test_archive_offers_errors(self):
        with self.assertRaises(management.CommandError):
            management.call_command(
                "archive_offers",
                "-s",
                "not-valid-date",
                stdout=self.out,
                stderr=self.err,
            )

        with self.assertRaises(management.CommandError):
            management.call_command(
                "archive_offers",
                "-o",
                "/tmp/does/not/exist/",
                stdout=self.out,
                stderr=self.err,
            )

    @override_settings(
        STORAGES={
            "default": {
                "BACKEND": "django.core.files.storage.InMemoryStorage",
            },
            "staticfiles": {
                "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
            },
        }
    )
    @patch("django.db.connections")
    def test_archive_offers(self, conn_mock):
        management.call_command(
            "archive_offers",
            stdout=self.out,
            stderr=self.err,
        )

        output = self.out.getvalue()

        self.assertTrue("Successfully archived" in output)
        # This appears when there's no STORAGES["data"]
        self.assertTrue("Skipping copying offers" in output)
        self.assertFalse("Skipping deleting archived offers" in output)

        management.call_command(
            "archive_offers",
            "-d",
            stdout=self.out,
            stderr=self.err,
        )

        output = self.out.getvalue()
        self.assertTrue("Skipping deleting archived offers" in output)

    @override_settings(
        STORAGES={
            "default": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": "/tmp/tmpmedia"},
            },
            "staticfiles": {
                "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
            },
            "data": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": "/tmp/tmpdata"},
            },
        }
    )
    @patch("django.db.connections")
    def test_archive_offers_storage(self, conn_mock):
        management.call_command(
            "archive_offers",
            "-d",
            stdout=self.out,
            stderr=self.err,
        )

        output = self.out.getvalue()
        self.assertFalse("Skipping deleting archived offers" in output)
        self.assertTrue("Copying offers" in output)
        self.assertTrue("Successfully copied" in output)
        self.assertTrue("Deleting archived offers" in output)
        self.assertTrue("Updating database statistics" in output)

        management.call_command(
            "archive_offers",
            "-d",
            stdout=self.out,
            stderr=self.err,
        )

        output = self.out.getvalue()
        self.assertTrue("already exists in backups" in output)


class TestExportD1Sql(TestCase):
    def setUp(self):
        self.publisher_active = get(
            Publisher,
            name="Active Publisher",
            slug="active-pub",
            disabled=False,
            default_keywords="python,django",
            revenue_share_percentage=75.0,
            send_bid_rate=True,
            ignore_mobile_traffic=True,
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
            cpc=1.25,
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
        out = io.StringIO()
        management.call_command("export_d1_sql", stdout=out)
        sql_content = out.getvalue()

        # Check publisher output
        self.assertIn("'active-pub'", sql_content)
        self.assertNotIn("'disabled-pub'", sql_content)
        self.assertIn(
            "revenue_share_percentage, send_bid_rate, ignore_mobile_traffic",
            sql_content,
        )
        self.assertIn("75.0, 1, 1", sql_content)

        # Check campaign output
        self.assertIn("'test-campaign'", sql_content)

        # Check ad_type output
        self.assertIn("'readthedocs-sidebar'", sql_content)

        # Check flight output
        self.assertIn("'active-flight'", sql_content)
        self.assertNotIn("'inactive-flight'", sql_content)
        self.assertIn("0.0, 1.25", sql_content)

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
        out = io.StringIO()
        management.call_command("export_d1_sql", max_urls=1, stdout=out)
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

        out = io.StringIO()
        management.call_command("export_d1_sql", stdout=out)
        sql_content = out.getvalue()

        # 2 existing active URLs + 105 new = 107 URLs
        # 107 URLs batched at 100/statement should produce exactly 2 INSERT statements for urls
        self.assertEqual(sql_content.count("INSERT OR REPLACE INTO urls"), 2)

    def test_export_to_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "test.sql"
            management.call_command("export_d1_sql", output=str(out_file))
            content = out_file.read_text(encoding="utf-8")
            self.assertIn("'active-pub'", content)
            self.assertIn("'active-flight'", content)
