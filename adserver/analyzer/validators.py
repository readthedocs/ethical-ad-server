"""Custom validators for the ad server analyzer."""

from django.core.exceptions import ValidationError
from django.core.validators import BaseValidator
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _


@deconstructible
class KeywordsValidator(BaseValidator):
    """A Django model and form validator for keyword analysis."""

    message = _("Enter a valid value")
    code = "keyword-validator"

    def __init__(self, message=None):
        """Initialization for the keyword validator."""
        if message:
            self.message = message

    def __call__(self, value):
        if not isinstance(value, list):
            raise ValidationError(
                _("Value must be a list, not %(type)s"), params={"type": type(value)}
            )

        if value:
            for keyword in value:
                if not isinstance(keyword, str) or keyword.lower() != keyword:
                    raise ValidationError(_("Each keyword must be a lowercase string"))
