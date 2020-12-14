import datetime

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.client import RequestFactory
from django_dynamic_fixture import get

from ..models import AdType
from ..models import Advertisement
from ..models import Advertiser
from ..models import Campaign
from ..models import Flight
from ..models import Publisher
from ..utils import get_ad_day


# Bytes representing a valid 1-pixel PNG
ONE_PIXEL_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
    b"\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02\x00\x00\x00\x0bIDATx"
    b"\x9cc\xfa\xcf\x00\x00\x02\x07\x01\x02\x9a\x1c1q\x00\x00\x00"
    b"\x00IEND\xaeB`\x82"
)


class BaseAdModelsTestCase(TestCase):
    def setUp(self):
        self.publisher = get(Publisher)
        self.advertiser = get(Advertiser)
        self.campaign = get(
            Campaign, advertiser=self.advertiser, publishers=[self.publisher]
        )
        self.flight = get(
            Flight,
            live=True,
            campaign=self.campaign,
            sold_clicks=1000,
            cpc=2.0,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            targeting_parameters={},
        )
        self.ad1 = get(
            Advertisement,
            name="Ad name 1",
            slug="ad-slug-1",
            link="http://example.com",
            live=True,
            image=None,
            text="<b>Test</b>",
            headline=None,
            body=None,
            cta=None,
            flight=self.flight,
        )
        self.ad2 = get(
            Advertisement,
            name="Ad name 2",
            slug="ad-slug-2",
            link="http://example.com",
            live=True,
            image=SimpleUploadedFile(
                name="test.png", content=ONE_PIXEL_PNG_BYTES, content_type="image/png"
            ),
            text="<b>Test</b>",
            headline=None,
            body=None,
            cta=None,
            flight=self.flight,
        )

        self.text_ad_type = get(
            AdType, has_text=True, max_text_length=100, has_image=False, template=None
        )
        self.image_ad_type = get(
            AdType,
            has_text=True,
            has_image=True,
            image_height=None,
            image_width=None,
            template=None,
        )

        self.staff_user = get(
            get_user_model(),
            is_staff=True,
            is_superuser=True,
            email="test-admin@example.com",
        )

        self.factory = RequestFactory()
