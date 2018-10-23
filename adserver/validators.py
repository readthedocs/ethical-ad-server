"""Custom validators for the ad server"""
from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _
from django_countries import countries


@deconstructible
class TargetingParametersValidator:

    """A Django model and form validator for validating ad targeting"""

    message = _("Enter a valid value")
    code = "targeting-validator"

    messages = {
        "invalid_type": _("Value must be a dict, not %(type)s"),
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
    }

    def __init__(self):
        """Initialization for the targeting validator"""
        self.country_set = {cc for cc, name in countries}

    def __call__(self, value):
        if value:
            if not isinstance(value, dict):
                raise ValidationError(
                    self.messages["invalid_type"], params={"type": type(value)}
                )

            for key in value:
                if key not in self.validators:
                    continue

                validator = self.validators[key]
                func = getattr(self, validator)
                func(value[key])

    def __eq__(self, other):
        """Required for serialization to migrations"""
        return (
            isinstance(other, TargetingParametersValidator)
            and (self.message == other.message)
            and (self.code == other.code)
        )

    def __ne__(self, other):
        """Required for serialization to migrations"""
        return not (self == other)

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
