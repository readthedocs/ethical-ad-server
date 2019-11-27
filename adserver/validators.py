"""Custom validators for the ad server."""
import bleach
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
    }

    def __init__(self, message=None):
        """Initialization for the targeting validator."""
        self.country_set = {cc for cc, name in countries}
        if message:
            self.message = message

    def __call__(self, value):
        if value:
            if not isinstance(value, dict):
                raise ValidationError(
                    self.messages["invalid_type"], params={"type": type(value)}
                )

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


@deconstructible
class AdvertisementValidator(BaseValidator):

    """Validates an advertisement given its ad type."""

    message = _("Enter a valid value")
    code = "advertisement-type"
    limit_value = None  # required for classes extending BaseValidator

    messages = {
        "missing_image": _("An image is required for '%(ad_type)s' ads"),
        "no_image": _("'%(ad_type)s' ads cannot have images"),
        "invalid_dimensions": _(
            "Images for '%(ad_type)s' ads must be %(ad_type_width)s * %(ad_type_height)s "
            "(it is %(width)s * %(height)s)"
        ),
        "text_too_long": _(
            "Text for '%(ad_type)s' ads must be %(ad_type_max_chars)s characters or less "
            "(it is %(text_len)s)"
        ),
    }

    def __init__(self, message=None):
        """Any initialization for the validator."""
        if message:
            self.message = message

    def __call__(self, value):
        advertisement = value
        self.clean(advertisement)

        if not advertisement or not advertisement.ad_type:
            return

        if advertisement.ad_type.has_image and not advertisement.image:
            raise ValidationError(
                self.messages["missing_image"],
                params={"ad_type": advertisement.ad_type},
            )
        if not advertisement.ad_type.has_image and advertisement.image:
            raise ValidationError(
                self.messages["no_image"], params={"ad_type": advertisement.ad_type}
            )

        # Check image size - allow @2x images (double height, double width)
        if advertisement.image and (
            advertisement.ad_type.image_width or advertisement.ad_type.image_height
        ):
            if (
                advertisement.image.width != advertisement.ad_type.image_width
                or advertisement.image.height != advertisement.ad_type.image_height
            ) and (
                advertisement.image.width // 2 != advertisement.ad_type.image_width
                or advertisement.image.height // 2 != advertisement.ad_type.image_height
            ):
                raise ValidationError(
                    self.messages["invalid_dimensions"],
                    params={
                        "ad_type": advertisement.ad_type,
                        "ad_type_width": advertisement.ad_type.image_width,
                        "ad_type_height": advertisement.ad_type.image_height,
                        "width": advertisement.image.width,
                        "height": advertisement.image.height,
                    },
                )

        # Check text length
        if advertisement.ad_type.max_text_length:
            stripped_text = bleach.clean(advertisement.text, tags=[], strip=True)
            if len(stripped_text) > advertisement.ad_type.max_text_length:
                raise ValidationError(
                    self.messages["text_too_long"],
                    params={
                        "ad_type": advertisement.ad_type,
                        "ad_type_max_chars": advertisement.ad_type.max_text_length,
                        "text_len": len(stripped_text),
                    },
                )

    def clean(self, x):
        ad = x
        allowed_tags = bleach.sanitizer.ALLOWED_TAGS
        if ad.ad_type:
            allowed_tags = ad.ad_type.allowed_html_tags.split()

        if ad.text:
            # Remove malicious HTML tags, inline styles, and fix broken tags
            ad.text = bleach.clean(ad.text, tags=allowed_tags, strip=True)
        return ad
