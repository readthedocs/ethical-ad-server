"""Forms for the ad server."""
import logging

import bleach
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from django import forms
from django.core.files.images import get_image_dimensions
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from django.utils.translation import ugettext_lazy as _

from .models import Advertisement
from .models import Flight


log = logging.getLogger(__name__)  # noqa


class FlightAdminForm(forms.ModelForm):

    """The form for flights used by the Django Admin."""

    class Meta:
        model = Flight

        # Denormalized fields total clicks and total views are ignored
        fields = (
            "name",
            "slug",
            "campaign",
            "start_date",
            "end_date",
            "live",
            "priority_multiplier",
            "cpc",
            "sold_clicks",
            "cpm",
            "sold_impressions",
            "targeting_parameters",
        )

    def clean(self):
        cpc = self.cleaned_data.get("cpc")
        cpm = self.cleaned_data.get("cpm")
        if cpc > 0 and cpm > 0:
            raise forms.ValidationError(_("A flight cannot have both CPC & CPM"))

        return self.cleaned_data


class AdvertisementFormMixin:

    """Common functionality shared by the admin form and the one used by advertisers."""

    messages = {
        "ad_type_required": _(
            "One or more ad type is required or the ad will never be displayed"
        ),
        "missing_image": _("An image is required for '%(ad_type)s' ads"),
        "invalid_dimensions": _(
            "Images for '%(ad_type)s' ads must be %(ad_type_width)s * %(ad_type_height)s "
            "(it is %(width)s * %(height)s)"
        ),
        "text_too_long": _(
            "Text for '%(ad_type)s' ads must be %(ad_type_max_chars)s characters or less "
            "(it is %(text_len)s)"
        ),
    }

    def clean_text(self):
        text = self.cleaned_data.get("text")
        if text and "<a>" not in text:
            text = f"<a>{text}</a>"
        return text

    def clean(self):
        """Validate advertisements before they're saved."""
        cleaned_data = super().clean()

        ad_types = cleaned_data.get("ad_types")
        image = cleaned_data.get("image")
        text = cleaned_data.get("text")

        if not ad_types:
            self.add_error(
                "ad_types", forms.ValidationError(self.messages["ad_type_required"])
            )
        else:
            # Clean HTML tags - this requires at least one ad type
            allowed_tags = set(ad_types[0].allowed_html_tags.split())
            for ad_type in ad_types:
                allowed_tags = allowed_tags.intersection(
                    ad_type.allowed_html_tags.split()
                )
            text = bleach.clean(text, tags=allowed_tags, strip=True)
            cleaned_data["text"] = text

        # Apply ad type specific validation
        for ad_type in ad_types:
            # If any of the chosen ad types require images,
            # fail validation if there is no image
            if ad_type.has_image and not image:
                self.add_error(
                    "image",
                    forms.ValidationError(
                        self.messages["missing_image"], params={"ad_type": ad_type}
                    ),
                )

            # Check image size - allow @2x images (double height, double width)
            if ad_type.has_image and image:
                width, height = get_image_dimensions(image)

                if all(
                    (
                        ad_type.image_width,
                        ad_type.image_height,
                        (
                            width != ad_type.image_width
                            or height != ad_type.image_height
                        ),
                        (
                            width // 2 != ad_type.image_width
                            or height // 2 != ad_type.image_height
                        ),
                    )
                ):
                    self.add_error(
                        "image",
                        forms.ValidationError(
                            self.messages["invalid_dimensions"],
                            params={
                                "ad_type": ad_type,
                                "ad_type_width": ad_type.image_width,
                                "ad_type_height": ad_type.image_height,
                                "width": width,
                                "height": height,
                            },
                        ),
                    )

            # Check text length
            if ad_type.max_text_length:
                stripped_text = bleach.clean(text, tags=[], strip=True)
                if len(stripped_text) > ad_type.max_text_length:
                    self.add_error(
                        "text",
                        forms.ValidationError(
                            self.messages["text_too_long"],
                            params={
                                "ad_type": ad_type,
                                "ad_type_max_chars": ad_type.max_text_length,
                                "text_len": len(stripped_text),
                            },
                        ),
                    )

        return cleaned_data


class AdvertisementAdminForm(AdvertisementFormMixin, forms.ModelForm):
    class Meta:
        model = Advertisement
        fields = "__all__"
        widgets = {"ad_types": forms.CheckboxSelectMultiple()}


class AdvertisementForm(AdvertisementFormMixin, forms.ModelForm):

    """Model form used by advertisers to edit ads."""

    def __init__(self, *args, **kwargs):
        """Add the form helper and customize the look of the form."""
        self.flight = None
        if "flight" in kwargs:
            self.flight = kwargs.pop("flight")

        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.add_input(Submit("submit", _("Save advertisement")))

        self.fields["name"].help_text = _(
            "A helpful name for the ad which is not displayed to site visitors."
        )
        self.fields["live"].help_text = _("Uncheck to disable this advertisement")
        self.fields["ad_types"].label = _("Display types")

    def generate_slug(self):
        campaign_slug = self.flight.campaign.slug
        slug = slugify(self.instance.name)
        if not slug.startswith(campaign_slug):
            slug = slugify(f"{campaign_slug}-{slug}")

        while Advertisement.objects.filter(slug=slug).exists():
            random_chars = get_random_string(3)
            slug = slugify(f"{slug}-{random_chars}")

        return slug

    def save(self, commit=True):
        if not self.instance.flight_id:
            self.instance.flight = self.flight
        if not self.instance.slug:
            # Only needed on create
            self.instance.slug = self.generate_slug()
        return super().save(commit)

    class Meta:
        model = Advertisement
        fields = ("name", "live", "ad_types", "image", "link", "text")
        widgets = {
            "image": forms.FileInput(),
            "ad_types": forms.CheckboxSelectMultiple(),
        }
