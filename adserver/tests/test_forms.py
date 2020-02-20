import datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django_dynamic_fixture import get

from ..forms import AdvertisementCreateForm
from ..forms import AdvertisementUpdateForm
from ..forms import FlightAdminForm
from ..models import AdType
from ..models import Advertisement
from ..models import Campaign
from ..models import Flight
from ..utils import get_ad_day
from ..validators import AdvertisementValidator
from .common import ONE_PIXEL_PNG_BYTES


class FormTests(TestCase):
    def setUp(self):
        self.campaign = get(Campaign, name="Test Campaign", slug="test-campaign")
        self.flight = get(Flight, name="Test Flight", campaign=self.campaign)
        self.ad = get(Advertisement, name="Test Ad", flight=self.flight)

    def test_flight_form(self):
        data = {
            "name": "Test Flight",
            "slug": "test-flight",
            "cpc": 1.0,
            "cpm": 1.0,
            "sold_clicks": 100,
            "sold_impressions": 100_000,
            "campaign": self.campaign.pk,
            "live": True,
            "priority_multiplier": 1,
            "start_date": get_ad_day().date(),
            "end_date": get_ad_day().date() + datetime.timedelta(days=2),
        }
        form = FlightAdminForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertEquals(
            form.errors["__all__"], ["A flight cannot have both CPC & CPM"]
        )

        # A flight can't have both a CPC & CPM
        data["cpc"] = 0.0
        form = FlightAdminForm(data=data)
        self.assertTrue(form.is_valid())

    def test_ad_update_form(self):
        data = {
            "name": "Test Ad",
            "link": "http://example.com",
            "image": None,
            "live": True,
            "text": "This is a test",
        }
        form = AdvertisementUpdateForm(data=data, instance=self.ad)
        self.assertTrue(form.is_valid())
        ad = form.save()

        self.assertEqual(ad.text, "<a>This is a test</a>")

    def test_ad_update_ad_type(self):
        text_ad_type = get(AdType, has_text=True, max_text_length=100, has_image=False)
        image_ad_type = get(
            AdType,
            has_text=True,
            has_image=True,
            image_height=None,
            image_width=None,
            max_text_length=100,
        )

        self.ad.ad_type = image_ad_type
        self.ad.save()

        data = {
            "name": "Test Ad",
            "link": "http://example.com",
            "image": SimpleUploadedFile(
                name="test.png", content=ONE_PIXEL_PNG_BYTES, content_type="image/png"
            ),
            "live": True,
            "text": "This is a test",
        }

        # Valid - image is present
        form = AdvertisementUpdateForm(data=data, instance=self.ad)
        self.assertTrue(form.is_valid())

        self.ad.ad_type = text_ad_type
        self.ad.image = None
        self.ad.save()

        # Valid - image is ignored
        form = AdvertisementUpdateForm(data=data, instance=self.ad)
        self.assertTrue(form.is_valid())

        self.ad.ad_type.max_text_length = 10
        self.ad.ad_type.save()

        # Invalid - text too long
        form = AdvertisementUpdateForm(data=data, instance=self.ad)
        self.assertFalse(form.is_valid())

        # This is a non-field error since it depends on the ad type
        self.assertEquals(
            form.errors["__all__"],
            [
                AdvertisementValidator.messages["text_too_long"]
                % {
                    "ad_type": str(self.ad.ad_type),
                    "ad_type_max_chars": self.ad.ad_type.max_text_length,
                    "text_len": len(data["text"]),
                }
            ],
        )

    def test_ad_create_form(self):
        data = {
            "name": "Test Ad",
            "link": "http://example.com",
            "image": None,
            "live": True,
            "text": "This is a test",
        }
        form = AdvertisementCreateForm(data=data, flight=self.flight)
        self.assertFalse(form.is_valid())  # Name exists
        self.assertEquals(form.errors["name"], ["An ad with this name already exists."])

        data["name"] = "Another test"
        form = AdvertisementCreateForm(data=data, flight=self.flight)
        self.assertTrue(form.is_valid())

        ad = form.save()
        self.assertEqual(ad.flight, self.flight)
        self.assertEqual(ad.slug, "test-campaign-another-test")
        self.assertEqual(ad.name, data["name"])
        self.assertEqual(ad.text, "<a>This is a test</a>")

        # Another test that would cause a slug collision
        data["name"] = "Another test!!"
        form = AdvertisementCreateForm(data=data, flight=self.flight)
        self.assertTrue(form.is_valid())
        ad = form.save()
        self.assertEqual(ad.flight, self.flight)
        self.assertEqual(ad.name, data["name"])
        self.assertNotEqual(ad.slug, "test-campaign-another-test")
        self.assertTrue(ad.slug.startswith("test-campaign-another-test-"))

        # Another with no need to rewrite the slug
        data["name"] = "Test Campaign Third Test"
        data["text"] = "a <a>test</a>"
        form = AdvertisementCreateForm(data=data, flight=self.flight)
        self.assertTrue(form.is_valid())
        ad = form.save()
        self.assertEqual(ad.slug, "test-campaign-third-test")
        self.assertEqual(ad.text, data["text"])
