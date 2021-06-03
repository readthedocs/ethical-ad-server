import io
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import management
from django.db import models
from django.test import override_settings
from django.test import TestCase

from ..constants import CLICKS
from ..constants import VIEWS
from ..models import AdImpression
from ..models import Advertisement
from ..models import Advertiser
from ..models import Campaign
from ..models import Click
from ..models import Flight
from ..models import Publisher
from .test_publisher_dashboard import TestPublisherDashboardViews


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


class TestAddPublisher(TestCase):
    def setUp(self):
        self.out = io.StringIO()

    def test_publisher_plus_user(self):
        email = "testuser@example-pub.com"
        publisher_name = "example-pub.com"
        keywords = "Python, Django"
        management.call_command(
            "add_publisher",
            "-e",
            email,
            "-s",
            publisher_name,
            "-k",
            keywords,
            stdout=self.out,
        )

        user = User.objects.filter(email=email).first()
        self.assertIsNotNone(user)
        self.assertEqual(user.publishers.count(), 1)

        publisher = user.publishers.all().first()
        self.assertEqual(publisher.name, publisher_name)
        self.assertEqual(publisher.keywords, ["python", "django"])


class TestPayouts(TestCase):
    def setUp(self):
        TestPublisherDashboardViews.setUp(self)

    @patch("builtins.input", return_value="y")
    def test_publisher_plus_user(self, mock_input):
        self.out = io.StringIO()
        for x in range(50):
            self.ad1.incr(VIEWS, self.publisher1)
            self.ad1.incr(CLICKS, self.publisher1)

        management.call_command("payouts", "--email", "--all", stdout=self.out)

        output = self.out.getvalue()

        self.assertIn("total=70.00", output)
        self.assertIn("first=True", output)

    @patch("builtins.input", return_value="y")
    def test_publisher_option(self, mock_input):
        self.out = io.StringIO()
        self.publisher1.payout_method = "payout"
        self.publisher1.stripe_connected_account_id = "test"
        self.publisher1.save()
        for x in range(50):
            self.ad1.incr(VIEWS, self.publisher1)
            self.ad1.incr(CLICKS, self.publisher1)

        management.call_command(
            "payouts",
            "--all",
            "--email",
            "--payout",
            "--publisher",
            self.publisher1.slug,
            stdout=self.out,
        )

        output = self.out.getvalue()

        self.assertIn(self.publisher1.slug, output)
        self.assertIn("total=70.00", output)
        self.assertIn("Create Payout?", output)
        self.assertIn("dashboard.stripe.com/connect/accounts/test", output)

    @patch("builtins.input", return_value="y")
    def test_publisher_low_ctr(self, mock_input):
        self.out = io.StringIO()
        for x in range(50):
            self.ad1.incr(VIEWS, self.publisher1)

        management.call_command("payouts", "--email", "--all", stdout=self.out)

        output = self.out.getvalue()

        self.assertIn("total=0.00", output)
        self.assertIn("first=True", output)

    @override_settings(FRONT_TOKEN="test", FRONT_CHANNEL="test", FRONT_AUTHOR="test")
    @patch("builtins.input", return_value="y")
    @patch("adserver.management.commands.payouts.requests.request")
    def test_publisher_email(self, requests_mock, mock_input):
        self.out = io.StringIO()
        for x in range(50):
            self.ad1.incr(VIEWS, self.publisher1)
            self.ad1.incr(CLICKS, self.publisher1)

        management.call_command(
            "payouts",
            "--all",
            "--send",
            "--publisher",
            self.publisher1.slug,
            stdout=self.out,
        )

        output = self.out.getvalue()

        self.assertEqual(
            requests_mock.call_args[0],
            ("POST", "https://api2.frontapp.com/channels/test/messages"),
        )
        self.assertIn(self.publisher1.slug, output)
        self.assertIn("total=70.00", output)


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

    @patch("django.db.connection")
    def test_archive_offers(self, conn_mock):
        management.call_command(
            "archive_offers",
            stdout=self.out,
            stderr=self.err,
        )

        output = self.out.getvalue()

        self.assertTrue("Successfully archived" in output)
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

    @override_settings(BACKUPS_STORAGE="django.core.files.storage.FileSystemStorage")
    @patch("django.db.connection")
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
