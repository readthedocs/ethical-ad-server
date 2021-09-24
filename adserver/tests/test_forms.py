import datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django_dynamic_fixture import get

from ..forms import AdvertisementForm
from ..forms import FlightAdminForm
from ..forms import FlightForm
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
        self.ad = get(
            Advertisement,
            name="Test Ad",
            flight=self.flight,
            text="",  # New style ad
            headline="Old Headline",
            content="Old Body",
            cta="Old CTA",
        )
        self.ad.ad_types.add(self.ad_type)

        self.old_style_ad = get(
            Advertisement,
            name="Test Ad",
            flight=self.flight,
            text="This is a test",
            headline="",
            content="",
            cta="",
        )
        self.old_style_ad.ad_types.add(self.ad_type)

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
            "headline": "Test Advertiser:",
            "content": "Compelling Copy...",
            "cta": "Buy Stuff Today!",
            "ad_types": [self.ad_type.pk],
        }
        self.files = {
            "image": SimpleUploadedFile(
                name="test.png", content=ONE_PIXEL_PNG_BYTES, content_type="image/png"
            )
        }

        # This is for use with `old_style_ad`
        self.old_style_ad_data = {
            "name": "Advertisement Test",
            "link": "http://example.com",
            "image": None,
            "live": True,
            "text": "This is a test",
            "ad_types": [self.ad_type.pk],
        }

    def test_admin_flight_form(self):
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

    def test_flight_form(self):
        data = {
            "cpc": 1.0,
            "cpm": 1.0,
            "sold_clicks": 100,
            "sold_impressions": 100_000,
            "live": True,
            "start_date": get_ad_day().date(),
            "end_date": get_ad_day().date() + datetime.timedelta(days=2),
            "include_countries": "",
            "exclude_countries": "",
            "include_keywords": "",
        }
        form = FlightForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertEquals(
            form.errors["__all__"], ["A flight cannot have both CPC & CPM"]
        )

        # A flight can't have both a CPC & CPM
        data["cpc"] = 0.0
        form = FlightForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

        # Invalid country code
        data["include_countries"] = "US, YY"
        form = FlightForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertEquals(
            form.errors["include_countries"], ["YY is not a valid country code"]
        )

        data["include_countries"] = "US ,  CN"
        form = FlightForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

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

        data = self.ad_data.copy()
        data["headline"] = ""
        data["content"] = (
            "This is precisely 100 characters if you count the number exactly. "
            "I know it's true because I counted"
        )
        data["cta"] = ""

        form = AdvertisementForm(
            data=data, files={}, instance=self.ad, flight=self.flight
        )
        self.assertTrue(form.is_valid(), form.errors)

        # Invalid - text too long
        data["headline"] = "1"
        form = AdvertisementForm(
            data=data, files={}, instance=self.ad, flight=self.flight
        )
        self.assertFalse(form.is_valid(), form.errors)

        expected_text = "{}{}{}".format(
            data["headline"],
            data["content"],
            data["cta"],
        )
        self.assertEquals(
            form.errors["content"],
            [
                AdvertisementForm.messages["text_too_long"]
                % {
                    "ad_type": str(self.ad_type),
                    "ad_type_max_chars": self.ad_type.max_text_length,
                    "text_len": len(expected_text),
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

    def test_multi_error(self):
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

        expected_text = "{}{}{}".format(
            self.ad_data["headline"],
            self.ad_data["content"],
            self.ad_data["cta"],
        )
        self.assertEquals(
            form.errors["content"],
            [
                AdvertisementForm.messages["text_too_long"]
                % {
                    "ad_type": str(self.image_ad_type),
                    "ad_type_max_chars": self.image_ad_type.max_text_length,
                    "text_len": len(expected_text),
                }
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
        self.ad_data["content"] = "a test"
        form = AdvertisementForm(data=self.ad_data, flight=self.flight)
        self.assertTrue(form.is_valid(), form.errors)
        ad = form.save()
        self.assertEqual(ad.slug, "test-campaign-third-test")
        self.assertEqual(ad.content, self.ad_data["content"])

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

    def test_content_required(self):
        # When this is a "new style" ad form, at least content of headline, content and CTA is required
        self.ad_data["content"] = ""
        form = AdvertisementForm(data=self.ad_data, flight=self.flight)
        self.assertFalse(form.is_valid())
        self.assertEquals(form.errors["content"], ["This field is required."])

    # Below are tests for old-style ads with a single text field instead of broken out
    # headline, content, and CTA
    def test_ad_form_add_link(self):
        text = self.old_style_ad_data["text"]
        form = AdvertisementForm(
            data=self.old_style_ad_data, flight=self.flight, instance=self.old_style_ad
        )
        self.assertTrue(form.is_valid(), form.errors)
        ad = form.save()

        self.assertEqual(ad.text, f"<a>{text}</a>")

    def test_ad_broken_html(self):
        # Ensures the ad validator is called by the form
        text = "<a>noendtag"
        self.old_style_ad_data["text"] = text
        form = AdvertisementForm(
            data=self.old_style_ad_data, flight=self.flight, instance=self.old_style_ad
        )
        self.assertTrue(form.is_valid(), form.errors)
        ad = form.save()
        self.assertEqual(ad.text, text + "</a>")

    def test_ad_malicious_html(self):
        text = '<script>alert("foo")</script>'
        self.old_style_ad_data["text"] = text
        form = AdvertisementForm(
            data=self.old_style_ad_data, flight=self.flight, instance=self.old_style_ad
        )
        self.assertTrue(form.is_valid(), form.errors)
        ad = form.save()
        self.assertEqual(ad.text, '<a>alert("foo")</a>')

    def test_ad_remove_inline_style(self):
        text = '<b style="color: red">text</b>'
        self.old_style_ad_data["text"] = text
        form = AdvertisementForm(
            data=self.old_style_ad_data, flight=self.flight, instance=self.old_style_ad
        )
        self.assertTrue(form.is_valid(), form.errors)
        ad = form.save()
        self.assertEqual(ad.text, "<a><b>text</b></a>")
