import datetime
import sqlite3
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from django_dynamic_fixture import get

from ..constants import PAID_CAMPAIGN
from ..models import AdType
from ..models import Advertisement
from ..models import Advertiser
from ..models import Campaign
from ..models import Flight
from ..models import Publisher
from ..utils import get_ad_day


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
