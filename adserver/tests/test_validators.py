from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django_dynamic_fixture import get

from ..models import AdType
from ..models import Advertisement
from ..models import Campaign
from ..models import Flight
from ..validators import AdvertisementValidator
from ..validators import TargetingParametersValidator
from .common import ONE_PIXEL_PNG_BYTES


class TestValidators(TestCase):
    def setUp(self):
        self.campaign = get(Campaign)
        self.flight = get(Flight, campaign=self.campaign)
        self.ad = get(
            Advertisement,
            image=None,
            ad_type=None,
            text="<b>Test</b>",
            flight=self.flight,
        )

        self.image = SimpleUploadedFile(
            name="test.png", content=ONE_PIXEL_PNG_BYTES, content_type="image/png"
        )

    def test_targeting_validator(self):
        validator = TargetingParametersValidator(message="Test Message")

        # Ok
        validator({})
        validator({"include_countries": ["US", "CA"]})
        validator({"exclude_countries": ["US", "CA"]})
        validator({"include_keywords": ["django", "vuejs"]})
        validator({"exclude_keywords": ["django", "vuejs"]})
        validator({"include_state_provinces": ["CA", "ID", "OR"]})
        validator({"include_metro_codes": [1, 2]})

        # Unknown (old) parameters - these raise an error
        self.assertRaises(
            ValidationError, validator, {"include_programming_languages": ["py", "js"]}
        )
        self.assertRaises(
            ValidationError,
            validator,
            {"exclude_programming_languages": ["py", "words"]},
        )
        self.assertRaises(ValidationError, validator, {"include_projects": [1, 2]})
        self.assertRaises(
            ValidationError, validator, {"include_themes": ["alabaster", "rtd"]}
        )
        self.assertRaises(
            ValidationError, validator, {"include_builders": ["sphinx", "mkdocs"]}
        )

        # Invalid
        self.assertRaises(ValidationError, validator, "str")
        self.assertRaises(ValidationError, validator, [])
        self.assertRaises(ValidationError, validator, {"include_countries": "ZZ"})
        self.assertRaises(ValidationError, validator, {"include_keywords": [1]})
        self.assertRaises(
            ValidationError, validator, {"include_state_provinces": ["USA"]}
        )
        self.assertRaises(ValidationError, validator, {"include_metro_codes": ["USA"]})

    def test_ad_validator(self):
        text_ad_type = get(AdType, has_text=True, max_text_length=10, has_image=False)
        image_ad_type = get(
            AdType, has_text=False, has_image=True, image_height=None, image_width=None
        )
        validator = AdvertisementValidator(message="Test message")

        # Ok
        validator(self.ad)

        # Text ad
        self.ad.ad_type = text_ad_type
        validator(self.ad)

        # Text ad with image
        self.ad.image = self.image
        self.assertRaises(ValidationError, validator, self.ad)
        self.ad.image = None
        validator(self.ad)

        # Text too long
        self.ad.text = "*" * 100
        self.assertRaises(ValidationError, validator, self.ad)
        self.ad.ad_type.max_text_length = None
        self.ad.ad_type.save()
        validator(self.ad)

        # Invalid tags
        self.ad.text = "<script /><b>Hi</b>"
        validator(self.ad)
        self.assertEqual(self.ad.text, "<b>Hi</b>")

        # Image ad - missing image
        self.ad.text = ""
        self.ad.ad_type = image_ad_type
        self.assertRaises(ValidationError, validator, self.ad)
        self.ad.image = self.image
        validator(self.ad)

        # Ok
        image_ad_type.image_height = 1
        image_ad_type.image_width = 1
        validator(self.ad)

        # Image incorrect dimensions
        image_ad_type.image_height = 3
        image_ad_type.image_width = 3
        self.assertRaises(ValidationError, validator, self.ad)
