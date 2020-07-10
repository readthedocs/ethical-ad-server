import datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django_dynamic_fixture import get

from ..forms import AdvertisementForm
from ..forms import FlightAdminForm
from ..models import AdType
from ..models import Advertisement
from ..models import Campaign
from ..models import Flight
from ..utils import get_ad_day
from .common import ONE_PIXEL_PNG_BYTES


class FormTests(TestCase):
    def setUp(self):
        self.campaign = get(Campaign, name="Test Campaign", slug="test-campaign")
        self.flight = get(Flight, name="Test Flight", campaign=self.campaign)
        self.ad_type = get(AdType, has_text=True, max_text_length=100, has_image=False)
        self.ad = get(Advertisement, name="Test Ad", flight=self.flight)
        self.ad.ad_types.add(self.ad_type)

        self.image_ad_type = get(
            AdType,
            has_text=True,
            has_image=True,
            image_height=None,
            image_width=None,
            max_text_length=100,
        )

        self.ad_data = {
            "name": "Advertisement Test",
            "link": "http://example.com",
            "image": None,
            "live": True,
            "text": "This is a test",
            "ad_types": [self.ad_type.pk],
        }
        self.files = {
            "image": SimpleUploadedFile(
                name="test.png", content=ONE_PIXEL_PNG_BYTES, content_type="image/png"
            )
        }

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

    def test_ad_type_required(self):
        self.ad_data["ad_types"] = []
        form = AdvertisementForm(
            data=self.ad_data, files={}, instance=self.ad, flight=self.flight
        )

        self.assertFalse(form.is_valid(), form.errors)
        self.assertEquals(
            form.errors["ad_types"], [AdvertisementForm.messages["ad_type_required"]]
        )

    def test_text_too_long(self):
        # Valid text-only ad
        form = AdvertisementForm(
            data=self.ad_data, files={}, instance=self.ad, flight=self.flight
        )
        self.assertTrue(form.is_valid(), form.errors)

        # Shorten the maximum allowed text to test text too long
        self.ad_type.max_text_length = 10
        self.ad_type.save()

        # Invalid - text too long
        form = AdvertisementForm(
            data=self.ad_data, instance=self.ad, flight=self.flight
        )
        self.assertFalse(form.is_valid(), form.errors)

        self.assertEquals(
            form.errors["text"],
            [
                AdvertisementForm.messages["text_too_long"]
                % {
                    "ad_type": str(self.ad_type),
                    "ad_type_max_chars": self.ad_type.max_text_length,
                    "text_len": len(self.ad_data["text"]),
                }
            ],
        )

    def test_text_ad_with_image(self):
        # This is OK
        form = AdvertisementForm(
            data=self.ad_data, files=self.files, instance=self.ad, flight=self.flight
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNotNone(form.cleaned_data.get("image"))

    def test_image_missing(self):
        self.image_ad_type.max_text_length = 10
        self.image_ad_type.save()
        self.ad_data["ad_types"] = [self.image_ad_type.pk]
        form = AdvertisementForm(data=self.ad_data, files={}, flight=self.flight)
        self.assertFalse(form.is_valid(), form.errors)

        self.assertEquals(
            form.errors["image"],
            [
                AdvertisementForm.messages["missing_image"]
                % {"ad_type": str(self.image_ad_type)}
            ],
        )

        self.assertEquals(
            form.errors["text"],
            [
                AdvertisementForm.messages["text_too_long"]
                % {
                    "ad_type": str(self.image_ad_type),
                    "ad_type_max_chars": self.image_ad_type.max_text_length,
                    "text_len": len(self.ad_data["text"]),
                }
            ],
        )

    def test_multi_error(self):
        self.ad_data["ad_types"] = [self.image_ad_type.pk]
        form = AdvertisementForm(data=self.ad_data, files={}, flight=self.flight)
        self.assertFalse(form.is_valid(), form.errors)

        self.assertEquals(
            form.errors["image"],
            [
                AdvertisementForm.messages["missing_image"]
                % {"ad_type": str(self.image_ad_type)}
            ],
        )

    def test_image_dimensions(self):
        self.image_ad_type.image_width = 1
        self.image_ad_type.image_height = 1
        self.image_ad_type.save()
        self.ad_data["ad_types"] = [self.image_ad_type.pk]

        form = AdvertisementForm(
            data=self.ad_data, files=self.files, instance=self.ad, flight=self.flight
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNotNone(form.cleaned_data.get("image"))

        # Set the required dimensions to something else
        self.image_ad_type.image_width = 3
        self.image_ad_type.image_height = 3
        self.image_ad_type.save()
        self.ad_data["ad_types"] = [self.image_ad_type.pk]

        form = AdvertisementForm(
            data=self.ad_data, files=self.files, instance=self.ad, flight=self.flight
        )
        self.assertFalse(form.is_valid(), form.errors)
        self.assertEquals(
            form.errors["image"],
            [
                AdvertisementForm.messages["invalid_dimensions"]
                % {
                    "ad_type": str(self.image_ad_type),
                    "ad_type_width": self.image_ad_type.image_width,
                    "ad_type_height": self.image_ad_type.image_height,
                    "width": 1,
                    "height": 1,
                }
            ],
        )

    def test_ad_create_form(self):
        self.ad_data["name"] = "Another test!!"

        # Test that the slug gets the campaign prepended
        form = AdvertisementForm(data=self.ad_data, flight=self.flight)
        self.assertTrue(form.is_valid(), form.errors)
        ad = form.save()
        self.assertEqual(ad.flight, self.flight)
        self.assertEqual(ad.name, self.ad_data["name"])
        self.assertEqual(ad.slug, "test-campaign-another-test")

        # Save an ad with the same name and make sure the slug is made unique
        form = AdvertisementForm(data=self.ad_data, flight=self.flight)
        self.assertTrue(form.is_valid(), form.errors)
        ad = form.save()
        self.assertEqual(ad.flight, self.flight)
        self.assertEqual(ad.name, self.ad_data["name"])
        self.assertTrue(ad.slug.startswith("test-campaign-another-test-"))

        # Another with no need to rewrite the slug
        self.ad_data["name"] = "Test Campaign Third Test"
        self.ad_data["text"] = "a <a>test</a>"
        form = AdvertisementForm(data=self.ad_data, flight=self.flight)
        self.assertTrue(form.is_valid(), form.errors)
        ad = form.save()
        self.assertEqual(ad.slug, "test-campaign-third-test")
        self.assertEqual(ad.text, self.ad_data["text"])

    def test_ad_form_add_link(self):
        text = "This is a test"
        self.ad_data["text"] = text
        form = AdvertisementForm(data=self.ad_data, flight=self.flight)
        self.assertTrue(form.is_valid(), form.errors)
        ad = form.save()

        self.assertEqual(ad.text, f"<a>{text}</a>")

    def test_ad_broken_html(self):
        # Ensures the ad validator is called by the form
        text = "<a>noendtag"
        self.ad_data["text"] = text
        form = AdvertisementForm(data=self.ad_data, flight=self.flight)
        self.assertTrue(form.is_valid(), form.errors)
        ad = form.save()
        self.assertEqual(ad.text, text + "</a>")

    def test_ad_malicious_html(self):
        text = '<script>alert("foo")</script>'
        self.ad_data["text"] = text
        form = AdvertisementForm(data=self.ad_data, flight=self.flight)
        self.assertTrue(form.is_valid(), form.errors)
        ad = form.save()
        self.assertEqual(ad.text, '<a>alert("foo")</a>')

    def test_ad_remove_inline_style(self):
        text = '<b style="color: red">text</b>'
        self.ad_data["text"] = text
        form = AdvertisementForm(data=self.ad_data, flight=self.flight)
        self.assertTrue(form.is_valid(), form.errors)
        ad = form.save()
        self.assertEqual(ad.text, "<a><b>text</b></a>")

    def test_ad_multiple_ad_types(self):
        self.ad_data["ad_types"] = [self.ad_type.pk, self.image_ad_type.pk]
        form = AdvertisementForm(data=self.ad_data, files={}, flight=self.flight)
        self.assertFalse(form.is_valid(), form.errors)

        self.assertEquals(
            form.errors["image"],
            [
                AdvertisementForm.messages["missing_image"]
                % {"ad_type": str(self.image_ad_type)}
            ],
        )

        form = AdvertisementForm(
            data=self.ad_data, files=self.files, flight=self.flight
        )
        self.assertTrue(form.is_valid(), form.errors)
