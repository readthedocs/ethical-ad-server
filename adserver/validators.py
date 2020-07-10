"""Custom validators for the ad server."""
from django.core.exceptions import ValidationError
from django.core.validators import BaseValidator
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _
from django_countries import countries


@deconstructible
class TargetingParametersValidator(BaseValidator):

    """A Django model and form validator for validating ad targeting."""

    message = _("Enter a valid value")
    code = "targeting-validator"
    limit_value = None  # required for classes extending BaseValidator

    messages = {
        "invalid_type": _("Value must be a dict, not %(type)s"),
        "unknown_key": _("%(key)s is not a valid targeting parameter"),
        "country_code": _("%(code)s is not a valid country code"),
        "state_province_code": _("%(code)s is not a valid state/province code"),
        "metro_code": _("%(code)s is not a valid metro code"),
        "str": _("%(word)s must be a string"),
    }

    validators = {
        "include_countries": "_validate_country_codes",
        "include_state_provinces": "_validate_state_provinces",
        "include_metro_codes": "_validate_metro_codes",
        "exclude_countries": "_validate_country_codes",
        "include_keywords": "_validate_strs",
        "exclude_keywords": "_validate_strs",
    }

    def __init__(self, message=None):
        """Initialization for the targeting validator."""
        self.country_set = {cc for cc, name in countries}
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

    def _validate_strs(self, words):
        for word in words:
            if not isinstance(word, str):
                raise ValidationError(self.messages["str"], params={"word": word})
