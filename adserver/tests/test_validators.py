from django.core.exceptions import ValidationError
from django.test import TestCase
from django_dynamic_fixture import get

from ..models import Advertisement
from ..models import Campaign
from ..models import Flight
from ..validators import TargetingParametersValidator
from ..validators import TopicPricingValidator
from ..validators import TrafficFillValidator


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
        validator({"include_regions": ["us-ca", "eu"]})
        validator({"exclude_regions": ["exclude"]})
        validator({"include_topics": ["blockchain"]})

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
        self.assertRaises(
            ValidationError, validator, {"include_topics": ["invalid-topic"]}
        )

        # Niche targeting
        validator({"niche_targeting": 0.5})
        self.assertRaises(ValidationError, validator, {"niche_targeting": "invalid"})
        self.assertRaises(ValidationError, validator, {"niche_targeting": 1.1})
        self.assertRaises(ValidationError, validator, {"niche_targeting": -0.1})

        # Days
        validator({"days": ["monday", "tuesday"]})
        self.assertRaises(ValidationError, validator, {"days": ["not-a-day"]})

    def test_traffic_cap_validator(self):
        validator = TrafficFillValidator(message="Test Message")

        validator({})
        validator({"countries": {"US": 0.1, "CA": 0.1}})
        validator({"regions": {"us-ca": 0.1}})
        validator({"publishers": {"pub-slug": 0.1}})

        # Invalid
        self.assertRaises(
            ValidationError, validator, {"regions": {"invalid-region": 0.1}}
        )

        # Percentages
        self.assertRaises(ValidationError, validator, {"countries": {"US": 1.1}})
        self.assertRaises(ValidationError, validator, {"countries": {"US": -0.1}})
        self.assertRaises(ValidationError, validator, {"countries": {"US": "invalid"}})

    def test_region_validator_failures(self):
        validator = TargetingParametersValidator()
        self.assertRaises(
            ValidationError, validator, {"include_regions": ["invalid-region"]}
        )

    def test_country_validator_failures(self):
        validator = TrafficFillValidator()
        self.assertRaises(ValidationError, validator, {"countries": {"ZZ": 0.1}})
        self.assertRaises(ValidationError, validator, {"countries": {"US": 1.1}})
        self.assertRaises(ValidationError, validator, {"countries": {"US": -0.1}})
        self.assertRaises(ValidationError, validator, {"regions": {"us-ca": 1.1}})
        self.assertRaises(ValidationError, validator, {"publishers": {"pub-slug": 1.1}})

        # Types
        self.assertRaises(ValidationError, validator, {"publishers": {123: 0.1}})


class TestTopicPricingValidator(TestCase):
    def test_targeting_validator(self):
        validator = TopicPricingValidator(message="Test Message")

        # Ok
        validator({})
        validator({"devops": 2.5})
        validator({"devops": 2.5, "security-privacy": 2.0})

        # Invalid
        self.assertRaises(ValidationError, validator, "str")
        self.assertRaises(ValidationError, validator, [])
        self.assertRaises(ValidationError, validator, {"unknown-topic": 5.0})
        self.assertRaises(
            ValidationError, validator, {"security-privacy": "invalid-type"}
        )
        self.assertRaises(ValidationError, validator, {"security-privacy": -1.0})
