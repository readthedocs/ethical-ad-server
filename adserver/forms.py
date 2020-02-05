"""Forms for the ad server."""
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from django import forms
from django.forms.widgets import FileInput
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from django.utils.translation import ugettext_lazy as _

from .models import Advertisement
from .models import Flight


class FlightAdminForm(forms.ModelForm):

    """The form for flights used by the Django Admin."""

    class Meta:
        model = Flight
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


class AdvertisementUpdateForm(forms.ModelForm):

    """Model form used to edit ads."""

    def __init__(self, *args, **kwargs):
        """Add the form helper and customize the look of the form."""
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.add_input(Submit("submit", _("Save advertisement")))

        self.fields["name"].help_text = _(
            "A helpful name for the ad which is not displayed to site visitors."
        )
        self.fields["live"].help_text = _("Uncheck to disable this advertisement")
        if self.instance and self.instance.ad_type:
            self.fields["image"].help_text = self.get_image_help_text(
                self.instance.ad_type
            )
            self.fields["text"].help_text = self.get_text_help_text(
                self.instance.ad_type
            )

            if not self.instance.ad_type.has_image:
                del self.fields["image"]

    def get_image_help_text(self, ad_type):
        if not ad_type:
            return self.fields["image"].help_text

        if ad_type.image_width and ad_type.image_height:
            return _(
                "To replace the existing image, choose a new one sized to %(width)spx * %(height)spx."
            ) % {"width": ad_type.image_width, "height": ad_type.image_height}

        # This is not recommended!
        return _("Any image size is supported")

    def get_text_help_text(self, ad_type):
        if not ad_type:
            return self.fields["text"].help_text

        text_help_texts = []
        if ad_type.max_text_length:
            text_help_texts.append(
                _("Up to %(chars)s characters of text (excluding HTML).")
                % {"chars": ad_type.max_text_length}
            )
        if ad_type.allowed_html_tags:
            text_help_texts.append(
                _("Allowed HTML tags: %(tags)s.") % {"tags": ad_type.allowed_html_tags}
            )

        return " ".join(text_help_texts)

    def clean_text(self):
        text = self.cleaned_data.get("text")
        if text and "<a>" not in text:
            text = f"<a>{text}</a>"
        return text

    class Meta:
        model = Advertisement
        fields = ("name", "live", "image", "link", "text")
        widgets = {"image": FileInput()}


class AdvertisementCreateForm(AdvertisementUpdateForm):

    """Form for creating a new advertisement for an advertiser."""

    def __init__(self, *args, **kwargs):
        """Save the ad flight for later use."""
        self.flight = kwargs.pop("flight")
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data.get("name")
        if (
            Advertisement.objects.filter(
                flight__campaign__advertiser=self.flight.campaign.advertiser
            )
            .filter(name=name)
            .exists()
        ):
            raise forms.ValidationError(_("An ad with this name already exists."))
        return name

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
        self.instance.flight = self.flight
        self.instance.slug = self.generate_slug()
        return super().save(commit)

    class Meta:
        model = Advertisement
        fields = ("name", "live", "ad_type", "image", "link", "text")
