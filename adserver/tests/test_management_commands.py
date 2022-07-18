import io
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import management
from django.db import models
from django.test import override_settings
from django.test import TestCase

from ..models import AdImpression
from ..models import Advertisement
from ..models import Advertiser
from ..models import Campaign
from ..models import Click
from ..models import Flight
from ..models import Publisher


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

    @patch("django.db.connections")
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
