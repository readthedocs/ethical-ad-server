"""Custom validators for the ad server."""
from django.core.exceptions import ValidationError
from django.core.validators import BaseValidator
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _

from .utils import COUNTRY_DICT


@deconstructible
class TargetingParametersValidator(BaseValidator):

    """A Django model and form validator for validating ad targeting."""

    message = _("Enter a valid value")
    code = "targeting-validator"
    limit_value = None  # required for classes extending BaseValidator

    mobile_traffic_values = ("exclude", "only")

    messages = {
        "invalid_type": _("Value must be a dict, not %(type)s"),
        "unknown_key": _("%(key)s is not a valid key"),
        "country_code": _("%(code)s is not a valid country code"),
        "state_province_code": _("%(code)s is not a valid state/province code"),
        "metro_code": _("%(code)s is not a valid metro code"),
        "region": _("%(value)s is not a valid region"),
        "topic": _("%(value)s is not a valid topic"),
        "mobile": _(f"%(value)s must be one of {mobile_traffic_values}"),
        "str": _("%(word)s must be a string"),
        "percent": _("%(value)s must be a float between [0.0, 1.0]"),
    }

    validators = {
        "include_countries": "_validate_country_codes",
        "include_state_provinces": "_validate_state_provinces",
        "include_metro_codes": "_validate_metro_codes",
        "exclude_countries": "_validate_country_codes",
        "include_regions": "_validate_regions",
        "exclude_regions": "_validate_regions",
        "include_topics": "_validate_topics",
        "include_keywords": "_validate_strs",
        "exclude_keywords": "_validate_strs",
        "include_publishers": "_validate_strs",
        "exclude_publishers": "_validate_strs",
        "include_domains": "_validate_strs",
        "exclude_domains": "_validate_strs",
        "mobile_traffic": "_validate_mobile",
    }

    def __init__(self, message=None):
        """Initialization for the targeting validator."""
        self.country_set = set(COUNTRY_DICT)
        if message:
            self.message = message

    def __call__(self, value):
        if not isinstance(value, dict):
            raise ValidationError(
                self.messages["invalid_type"], params={"type": type(value)}
            )

        if value:
            for key in value:
                if key not in self.validators:
                    raise ValidationError(
                        self.messages["unknown_key"], params={"key": key}
                    )

                validator = self.validators[key]
                func = getattr(self, validator)
                func(value[key])

    def _validate_country_codes(self, codes):
        for code in codes:
            if code not in self.country_set:
                raise ValidationError(
                    self.messages["country_code"], params={"code": code}
                )

    def _validate_state_provinces(self, codes):
        for code in codes:
            if not isinstance(code, str) or len(code) != 2:
                raise ValidationError(
                    self.messages["state_province_code"], params={"code": code}
                )

    def _validate_metro_codes(self, codes):
        for code in codes:
            if not isinstance(code, int):
                raise ValidationError(
                    self.messages["metro_code"], params={"code": code}
                )

    def _validate_mobile(self, value):
        if value not in self.mobile_traffic_values:
            raise ValidationError(self.messages["mobile"], params={"value": value})

    def _validate_regions(self, region_values):
        from .models import Region  # noqa

        regions = Region.load_from_cache()
        for slug in region_values:
            if slug not in regions:
                raise ValidationError(self.messages["region"], params={"value": slug})

    def _validate_topics(self, slugs):
        from .models import Topic  # noqa

        topics = Topic.load_from_cache()
        for slug in slugs:
            if slug not in topics:
                raise ValidationError(self.messages["topic"], params={"value": slug})

    def _validate_strs(self, words):
        for word in words:
            if not isinstance(word, str):
                raise ValidationError(self.messages["str"], params={"word": word})


@deconstructible
class TrafficFillValidator(TargetingParametersValidator):

    """
    Validator for traffic fill and cap data.

    eg.
      {
        "publishers": {"publisher1": 0.1, "publisher2": 0.05},
        "countries": {"us": 0.1, "ca": 0.05, "de": 0.05},
        "regions": {"us-ca": 0.25, "eu": 0.5},
      }
    """

    code = "traffic-validator"

    validators = {
        "countries": "_validate_countries",
        "regions": "_validate_regions",
        "publishers": "_validate_publishers",
    }

    def _validate_countries(self, country_values):
        for code, value in country_values.items():
            if code not in self.country_set:
                raise ValidationError(
                    self.messages["country_code"], params={"code": code}
                )

            if not isinstance(value, float) or value > 1.0 or value < 0:
                raise ValidationError(self.messages["percent"], params={"value": value})

    def _validate_regions(self, region_values):
        from .models import Region  # noqa

        regions = Region.load_from_cache()
        for slug, value in region_values.items():
            if slug not in regions:
                raise ValidationError(self.messages["region"], params={"value": slug})

            if not isinstance(value, float) or value > 1.0 or value < 0:
                raise ValidationError(self.messages["percent"], params={"value": value})

    def _validate_publishers(self, publisher_values):
        for publisher_slug, value in publisher_values.items():
            if not isinstance(publisher_slug, str):
                raise ValidationError(
                    self.messages["str"], params={"word": publisher_slug}
                )

            if not isinstance(value, float) or value > 1.0 or value < 0:
                raise ValidationError(self.messages["percent"], params={"value": value})
