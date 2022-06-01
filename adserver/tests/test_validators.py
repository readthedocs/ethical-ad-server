from django.core.exceptions import ValidationError
from django.test import TestCase
from django_dynamic_fixture import get

from ..models import Advertisement
from ..models import Campaign
from ..models import Flight
from ..validators import TargetingParametersValidator


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

    def test_targeting_validator(self):
        validator = TargetingParametersValidator(message="Test Message")

        # Ok
        validator({})
        validator({"include_countries": ["US", "CA"]})
        validator({"exclude_countries": ["US", "CA"]})
        validator({"include_keywords": ["django", "vuejs"]})
        validator({"exclude_keywords": ["django", "vuejs"]})
        validator({"include_state_provinces": ["CA", "ID", "OR"]})
        validator({"include_publishers": ["slug1", "slug2"]})
        validator({"exclude_publishers": ["slug1", "slug2"]})
        validator({"include_domains": ["example.com", "www.example.com"]})
        validator({"exclude_domains": ["example.com", "www.example.com"]})
        validator({"include_metro_codes": [1, 2]})
        validator({"mobile_traffic": "exclude"})
        validator({"mobile_traffic": "only"})

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
        self.assertRaises(ValidationError, validator, {"mobile_traffic": "unknown"})
