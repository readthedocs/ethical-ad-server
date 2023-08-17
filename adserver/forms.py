"""Forms for the ad server."""
import logging
from datetime import timedelta

import bleach
import stripe
from crispy_forms.bootstrap import PrependedText
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div
from crispy_forms.layout import Field
from crispy_forms.layout import Fieldset
from crispy_forms.layout import HTML
from crispy_forms.layout import Layout
from crispy_forms.layout import Submit
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.shortcuts import get_current_site
from django.core.files.images import get_image_dimensions
from django.core.mail import EmailMessage
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.html import format_html
from django.utils.text import slugify
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from simple_history.utils import update_change_reason

from .models import Advertisement
from .models import Campaign
from .models import Flight
from .models import Publisher
from .models import Region
from .models import Topic
from .tasks import notify_on_ad_image_change
from .validators import TargetingParametersValidator


log = logging.getLogger(__name__)  # noqa
User = get_user_model()


class AdvertisementMultipleChoiceField(forms.ModelMultipleChoiceField):

    """
    Create a multiple choice field of advertisements with previews and additional data.

    The template should be able to handle being passed the full object
    as opposed to a string label.
    """

    def label_from_instance(self, obj):
        return obj


class FlightMixin:

    """Ensure the flight can't have both CPC and CPM."""

    def clean(self):
        cleaned_data = super().clean()
        cpc = cleaned_data.get("cpc") or 0
        cpm = cleaned_data.get("cpm") or 0
        if cpc > 0 and cpm > 0:
            raise forms.ValidationError(_("A flight cannot have both CPC & CPM"))

        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date >= end_date:
            raise forms.ValidationError(
                _("The end date must come after the start date")
            )

        return cleaned_data


class FlightAdminForm(FlightMixin, forms.ModelForm):

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
            "hard_stop",
            "live",
            "priority_multiplier",
            "pacing_interval",
            "prioritize_ads_ctr",
            "cpc",
            "sold_clicks",
            "cpm",
            "sold_impressions",
            "targeting_parameters",
            "traffic_fill",
            "traffic_cap",
        )


class FlightForm(FlightMixin, forms.ModelForm):

    """
    The form for flights used in a staff interface.

    The plan is to eventually make this a not-only-staff form.
    However, that would require a significant rework. Since different targeting is priced differently,
    we would need a way to let folks make adjustments and it automatically changes the price.
    """

    # This is just a helper field used in JavaScript to ease flight price computation
    # This field is *not* displayed in the Django admin because only fields in Meta.fields are displayed
    budget = forms.IntegerField(
        required=False,
        label=_("Budget"),
    )

    include_regions = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    exclude_regions = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    include_topics = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    include_countries = forms.CharField(
        max_length=1024,
        required=False,
        help_text=_("A comma separated list of country codes"),
    )
    exclude_countries = forms.CharField(
        max_length=1024,
        required=False,
        help_text=_("A comma separated list of country codes"),
    )
    include_keywords = forms.CharField(
        max_length=1024,
        required=False,
        help_text=_("A comma separated list of keywords"),
    )

    def __init__(self, *args, **kwargs):
        """Set the flight form helper and initial data."""
        super().__init__(*args, **kwargs)

        self.regions = Region.objects.all().order_by("order", "slug")
        self.topics = Topic.objects.all().order_by("slug")

        if self.instance.pk:
            self.fields["budget"].initial = round(self.instance.projected_total_value())
            self.fields["include_regions"].initial = self.instance.included_regions
            self.fields["exclude_regions"].initial = self.instance.excluded_regions
            self.fields["include_topics"].initial = self.instance.included_topics
            self.fields["include_countries"].initial = ", ".join(
                self.instance.included_countries
            )
            self.fields["exclude_countries"].initial = ", ".join(
                self.instance.excluded_countries
            )
            self.fields["include_keywords"].initial = ", ".join(
                self.instance.included_keywords
            )

        self.fields["include_regions"].choices = [
            (r.slug, r.name) for r in self.regions
        ]
        self.fields["exclude_regions"].choices = self.fields["include_regions"].choices
        self.fields["include_topics"].choices = [(t.slug, t.name) for t in self.topics]

        self.helper = FormHelper()
        self.helper.attrs = {"id": "flight-update-form"}

        self.helper.layout = Layout(
            Fieldset(
                "",
                Field("name"),
                Div(
                    Div("start_date", css_class="form-group col-lg-6"),
                    Div("end_date", css_class="form-group col-lg-6"),
                    css_class="form-row",
                ),
                "live",
                Div(
                    PrependedText(
                        "budget",
                        "$",
                        min=0,
                        data_bind="textInput: budget",
                    ),
                ),
                css_class="my-3",
            ),
            Fieldset(
                _("Per impression (CPM) flights"),
                Div(
                    Div(
                        PrependedText("cpm", "$", min=0, data_bind="textInput: cpm"),
                        css_class="form-group col-lg-6",
                    ),
                    Div(
                        Field(
                            "sold_impressions", data_bind="textInput: sold_impressions"
                        ),
                        css_class="form-group col-lg-6",
                    ),
                    css_class="form-row",
                ),
                css_class="my-3",
            ),
            Fieldset(
                _("Per click (CPC) flights"),
                Div(
                    Div(
                        PrependedText("cpc", "$", min=0, data_bind="textInput: cpc"),
                        css_class="form-group col-lg-6",
                    ),
                    Div(
                        Field("sold_clicks", data_bind="textInput: sold_clicks"),
                        css_class="form-group col-lg-6",
                    ),
                    css_class="form-row",
                ),
                css_class="my-3",
            ),
            # NOTE: remove this when this form is made for non-staff users
            Field("priority_multiplier"),
            Fieldset(
                _("Flight targeting"),
                Div("include_regions"),
                Div("exclude_regions"),
                Div("include_topics"),
                Div("include_countries"),
                Div("exclude_countries"),
                Div("include_keywords"),
                css_class="my-3",
            ),
            Submit("submit", _("Update flight")),
        )

    def clean_include_countries(self):
        data = self.cleaned_data["include_countries"]
        include_countries = [
            cc.strip() for cc in data.split(",") if len(cc.strip()) > 0
        ]
        if include_countries:
            TargetingParametersValidator()({"include_countries": include_countries})
        return data

    def clean_exclude_countries(self):
        data = self.cleaned_data["exclude_countries"]
        exclude_countries = [
            cc.strip() for cc in data.split(",") if len(cc.strip()) > 0
        ]
        if exclude_countries:
            TargetingParametersValidator()({"exclude_countries": exclude_countries})
        return data

    def clean_include_keywords(self):
        data = self.cleaned_data["include_keywords"].lower()
        include_keywords = [kw.strip() for kw in data.split(",") if len(kw.strip()) > 0]
        if include_keywords:
            TargetingParametersValidator()({"include_keywords": include_keywords})
        return data

    def save(self, commit=True):
        if not self.instance.targeting_parameters:
            # This can happen if the flight was setup with no targeting at all
            self.instance.targeting_parameters = {}

        self.instance.targeting_parameters["include_regions"] = self.cleaned_data[
            "include_regions"
        ]
        self.instance.targeting_parameters["exclude_regions"] = self.cleaned_data[
            "exclude_regions"
        ]
        self.instance.targeting_parameters["include_topics"] = self.cleaned_data[
            "include_topics"
        ]
        self.instance.targeting_parameters["include_countries"] = [
            cc.strip()
            for cc in self.cleaned_data["include_countries"].split(",")
            if len(cc.strip()) > 0
        ]
        self.instance.targeting_parameters["exclude_countries"] = [
            cc.strip()
            for cc in self.cleaned_data["exclude_countries"].split(",")
            if len(cc.strip()) > 0
        ]
        self.instance.targeting_parameters["include_keywords"] = [
            kw.strip()
            for kw in self.cleaned_data["include_keywords"].split(",")
            if len(kw.strip()) > 0
        ]

        # TODO: handle rare targeting options (state/provinces, metro codes, exclude keywords, mobile traffic)
        # If a flight has one of these rare targeting options already, saving the form won't affect it

        # Handle when targeting is totally removed
        for key in (
            "include_countries",
            "exclude_countries",
            "include_keywords",
            "include_regions",
            "exclude_regions",
            "include_topics",
        ):
            if not self.instance.targeting_parameters[key]:
                del self.instance.targeting_parameters[key]

        return super().save(commit)

    class Meta:
        model = Flight

        fields = (
            "name",
            "start_date",
            "end_date",
            "live",
            "cpc",
            "sold_clicks",
            "cpm",
            "sold_impressions",
            "priority_multiplier",
        )
        widgets = {
            "start_date": forms.DateInput(
                attrs={"type": "date", "pattern": "[0-9]{4}-[0-9]{2}-[0-9]{2}"}
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "pattern": "[0-9]{4}-[0-9]{2}-[0-9]{2}"}
            ),
        }


class FlightCreateForm(forms.ModelForm):

    """Create a new flight for this advertiser."""

    def __init__(self, *args, **kwargs):
        """Set the flight form helper and initial data for creating a flight."""
        if "advertiser" in kwargs:
            self.advertiser = kwargs.pop("advertiser")
        else:
            raise RuntimeError("'advertiser' is required for the flight create form")

        super().__init__(*args, **kwargs)

        if "campaign" in self.fields:
            self.fields["campaign"].queryset = Campaign.objects.filter(
                advertiser=self.advertiser
            )
        self.helper = self.create_form_helper()

    def create_form_helper(self):
        helper = FormHelper()
        helper.layout = Layout(
            Fieldset(
                "",
                "name",
                "campaign",
                css_class="my-3",
            ),
            Submit("submit", _("Create flight")),
            HTML(
                "<p class='form-text small text-muted'>"
                + str(_("You will be able to edit details on the next screen"))
                + "</p>"
            ),
        )
        return helper

    def generate_slug(self):
        campaign_slug = self.instance.campaign.slug
        slug = slugify(self.instance.name)
        if not slug.startswith(campaign_slug):
            slug = slugify(f"{campaign_slug}-{slug}")

        while Flight.objects.filter(slug=slug).exists():
            random_char = get_random_string(1)
            slug = slugify(f"{slug}-{random_char}")

        return slug

    def save(self, commit=True):
        self.instance.advertiser = self.advertiser
        self.instance.slug = self.generate_slug()
        return super().save(commit)

    class Meta:
        model = Flight

        fields = (
            "name",
            "campaign",
        )


class FlightRenewForm(FlightMixin, FlightCreateForm):

    """Form class for creating a new flight via renewal."""

    advertisements = AdvertisementMultipleChoiceField(
        queryset=Advertisement.objects.none(),
        required=False,
        help_text=_("Renew the flight with the following advertisements"),
    )
    budget = forms.IntegerField(
        required=False,
        label=_("Budget"),
    )

    def __init__(self, *args, **kwargs):
        """Set the flight form helper and initial data for renewing a flight."""
        self.old_flight = kwargs.pop("flight")

        if "initial" not in kwargs:
            kwargs["initial"] = {}
        kwargs["initial"].update(
            {
                "budget": round(self.old_flight.projected_total_value()),
                "name": self.old_flight.name,
                "cpm": self.old_flight.cpm,
                "cpc": self.old_flight.cpc,
                "sold_clicks": self.old_flight.sold_clicks,
                "sold_impressions": self.old_flight.sold_impressions,
                "campaign": self.old_flight.campaign,
                "start_date": timezone.now().today(),
                "end_date": timezone.now().today()
                + (self.old_flight.end_date - self.old_flight.start_date),
                "advertisements": self.old_flight.advertisements.filter(live=True),
            }
        )

        # Sets self.advertiser
        super().__init__(*args, **kwargs)

        self.fields["advertisements"].queryset = self.old_flight.advertisements.all()

    def create_form_helper(self):
        helper = FormHelper()
        helper.attrs = {"id": "flight-renew-form"}
        helper.layout = Layout(
            Fieldset(
                "",
                Field("name"),
                Field("campaign"),
                Div(
                    Div("start_date", css_class="form-group col-lg-6"),
                    Div("end_date", css_class="form-group col-lg-6"),
                    css_class="form-row",
                ),
                "live",
                Div(
                    PrependedText(
                        "budget",
                        "$",
                        min=0,
                        data_bind="textInput: budget",
                    ),
                ),
                css_class="my-3",
            ),
            Fieldset(
                _("Per impression (CPM) flights"),
                Div(
                    Div(
                        PrependedText("cpm", "$", min=0, data_bind="textInput: cpm"),
                        css_class="form-group col-lg-6",
                    ),
                    Div(
                        Field(
                            "sold_impressions", data_bind="textInput: sold_impressions"
                        ),
                        css_class="form-group col-lg-6",
                    ),
                    css_class="form-row",
                ),
                css_class="my-3",
            ),
            Fieldset(
                _("Per click (CPC) flights"),
                Div(
                    Div(
                        PrependedText("cpc", "$", min=0, data_bind="textInput: cpc"),
                        css_class="form-group col-lg-6",
                    ),
                    Div(
                        Field("sold_clicks", data_bind="textInput: sold_clicks"),
                        css_class="form-group col-lg-6",
                    ),
                    css_class="form-row",
                ),
                css_class="my-3",
            ),
            Fieldset(
                _("Advertisements"),
                Field(
                    "advertisements",
                    template="adserver/includes/widgets/advertisement-form-option.html",
                ),
                css_class="my-3",
            ),
            Submit("submit", _("Create flight via renewal")),
        )
        return helper

    def save(self, commit=True):
        assert commit, "Delayed saving is not supported on this form"

        instance = super().save(commit)

        # Copy flight fields that aren't part of the form
        for field in ("targeting_parameters", "priority_multiplier", "traffic_cap"):
            setattr(instance, field, getattr(self.old_flight, field))
        instance.save()

        # Duplicate the advertisements into the new flight
        for ad in self.cleaned_data["advertisements"]:
            new_ad = ad.__copy__()
            new_ad.flight = instance
            new_ad.live = True
            new_ad.save()  # Automatically gets a new slug

        return instance

    class Meta:
        model = Flight

        fields = (
            "name",
            "campaign",
            "start_date",
            "end_date",
            "live",
            "cpc",
            "sold_clicks",
            "cpm",
            "sold_impressions",
        )
        widgets = {
            "start_date": forms.DateInput(
                attrs={"type": "date", "pattern": "[0-9]{4}-[0-9]{2}-[0-9]{2}"}
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "pattern": "[0-9]{4}-[0-9]{2}-[0-9]{2}"}
            ),
        }


class FlightRequestForm(FlightCreateForm):

    """Used by advertisers to request a new flight."""

    advertisements = AdvertisementMultipleChoiceField(
        queryset=Advertisement.objects.none(),
        required=False,
        help_text=_("Request a new flight with the following advertisements"),
    )

    budget = forms.IntegerField(
        label=_("Budget"),
    )

    note = forms.CharField(label=_("Note"), required=False, widget=forms.Textarea)

    DEFAULT_FLIGHT_BUDGET = 3_000

    def __init__(self, *args, **kwargs):
        """Set the flight form helper and initial data for renewing a flight."""
        self.old_flight = kwargs.pop("flight", None)

        advertiser = kwargs["advertiser"]
        default_name = f"{advertiser} - {timezone.now():%b %Y}"

        if "initial" not in kwargs:
            kwargs["initial"] = {}
        kwargs["initial"].update(
            {
                "budget": round(self.old_flight.projected_total_value())
                if self.old_flight
                else self.DEFAULT_FLIGHT_BUDGET,
                "name": default_name,
                "start_date": timezone.now().today(),
                "end_date": timezone.now().today()
                + (
                    (self.old_flight.end_date - self.old_flight.start_date)
                    if self.old_flight
                    else timedelta(days=30)
                ),
                "advertisements": self.old_flight.advertisements.filter(live=True)
                if self.old_flight
                else Advertisement.objects.none(),
            }
        )

        # Sets self.advertiser
        super().__init__(*args, **kwargs)

        self.fields["note"].widget.attrs["rows"] = 3
        self.fields["note"].help_text = _(
            "Do you have any changes you'd like to make from previous flights or any special instructions?"
        )
        self.fields["start_date"].help_text = _("The target start date for this flight")
        self.fields["end_date"].help_text = _(
            "The target end date for this flight (it may go after this date)"
        )
        self.fields["advertisements"].queryset = (
            self.old_flight.advertisements.all()
            if self.old_flight
            else Advertisement.objects.none()
        )

    def create_form_helper(self):
        helper = FormHelper()
        helper.attrs = {"id": "flight-request-form"}
        helper.layout = Layout(
            Fieldset(
                "",
                Field("name"),
                Div(
                    Div("start_date", css_class="form-group col-lg-6"),
                    Div("end_date", css_class="form-group col-lg-6"),
                    css_class="form-row",
                ),
                Div(
                    PrependedText(
                        "budget",
                        "$",
                        min=0,
                        data_bind="textInput: budget",
                    ),
                ),
                Field("note"),
                css_class="my-3",
            ),
            Fieldset(
                _("Advertisements"),
                Field(
                    "advertisements",
                    template="adserver/includes/widgets/advertisement-form-option.html",
                ),
                css_class="my-3",
            ),
            Submit("submit", _("Request a new flight")),
            HTML(
                "<p class='form-text small text-muted'>"
                + str(
                    _(
                        "Your flight will not start automatically. Your account manager will be notified to review your ads and targeting."
                    )
                )
                + "</p>"
            ),
        )
        return helper

    def save(self, commit=True):
        assert commit, "Delayed saving is not supported on this form"

        # This is already the default but we are setting it explicitly to be defensive
        self.instance.live = False

        if self.old_flight:
            # Copy fields not in the form from the old flight if possible
            # Otherwise, the account manager will need to set these
            fields = (
                "targeting_parameters",
                "priority_multiplier",
                "cpm",
                "cpc",
                "sold_impressions",
                "sold_clicks",
            )
            for field in fields:
                setattr(self.instance, field, getattr(self.old_flight, field))

        # We must set the campaign
        self.instance.campaign = (
            self.old_flight.campaign
            if self.old_flight
            else self.advertiser.campaigns.first()
        )

        instance = super().save(commit)

        # Duplicate the advertisements into the new flight
        if "advertisements" in self.cleaned_data:
            for ad in self.cleaned_data["advertisements"]:
                new_ad = ad.__copy__()
                new_ad.flight = instance
                new_ad.live = True
                new_ad.save()  # Automatically gets a new slug

        return instance

    class Meta:
        model = Flight

        fields = (
            "name",
            "start_date",
            "end_date",
        )
        widgets = {
            "start_date": forms.DateInput(
                attrs={"type": "date", "pattern": "[0-9]{4}-[0-9]{2}-[0-9]{2}"}
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "pattern": "[0-9]{4}-[0-9]{2}-[0-9]{2}"}
            ),
        }


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
            "Total text for '%(ad_type)s' ads must be %(ad_type_max_chars)s characters or less "
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

        # Old ads
        text = cleaned_data.get("text")

        # New ads
        headline = cleaned_data.get("headline") or ""
        content = cleaned_data.get("content")
        cta = cleaned_data.get("cta") or ""

        if not ad_types:
            self.add_error(
                "ad_types", forms.ValidationError(self.messages["ad_type_required"])
            )
        elif text:
            # Clean HTML tags on `text` - this requires at least one ad type
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
                if text:
                    stripped_text = bleach.clean(text, tags=[], strip=True)
                else:
                    stripped_text = f"{headline}{content}{cta}"

                if len(stripped_text) > ad_type.max_text_length:
                    self.add_error(
                        "text" if text else "content",
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
        if "flight" in kwargs:
            self.flight = kwargs.pop("flight")
        else:
            raise RuntimeError("'flight' is required for the ad form")

        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.attrs = {"id": "advertisement-update"}

        self.fields["name"].help_text = _(
            "A helpful name for the ad which is not displayed to site visitors."
        )
        self.fields["live"].help_text = _("Uncheck to disable this advertisement")
        self.fields["ad_types"].label = _("Display types")

        # Get global ad types and ad types that are specific to the publishers targeted by the campaign
        adtype_queryset = self.flight.campaign.allowed_ad_types()

        # Remove deprecated ad types unless the passed ad has those ad types
        if self.instance.pk:
            adtype_queryset = adtype_queryset.filter(
                Q(deprecated=False) | Q(pk__in=self.instance.ad_types.values("pk"))
            )
        else:
            adtype_queryset = adtype_queryset.exclude(deprecated=True)
        self.fields["ad_types"].queryset = adtype_queryset

        # Ads are now composed of `headline`, `content`, and `cta`
        # but some older ads are just an HTML blob of `text`.
        # Support legacy ads while making sure new ads follow the new convention
        if not self.instance.pk or self.instance.content:
            del self.fields["text"]
            self.fields["content"].widget.attrs["rows"] = 3
            self.fields["content"].required = True

            self.fields["headline"].widget.attrs["data-bind"] = "textInput: headline"
            self.fields["content"].widget.attrs["data-bind"] = "textInput: content"
            self.fields["cta"].widget.attrs["data-bind"] = "textInput: cta"
            ad_display_fields = ["headline", "content", "cta"]
        else:
            del self.fields["headline"]
            del self.fields["content"]
            del self.fields["cta"]
            self.fields["text"].widget.attrs["rows"] = 3
            self.fields["text"].required = True
            ad_display_fields = ["text"]

        self.helper.layout = Layout(
            Fieldset(
                "",
                "name",
                "live",
                css_class="my-3",
            ),
            Fieldset(
                _("Advertisement display"),
                "ad_types",
                "link",
                "image",
                css_class="my-3",
            ),
            Fieldset(
                _("Advertisement text"),
                Div(
                    HTML(
                        "<span data-bind='text: totalLength()'></span> total characters"
                    ),
                    # Only display on "new style" ads with the headline, content, and CTA
                    # Simply hide it on the old style ads.
                    data_bind="visible: totalLength() > 0",
                    css_class="small text-muted mb-2",
                ),
                *ad_display_fields,
            ),
            Submit("submit", _("Save advertisement")),
        )

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

        new_instance = super().save(commit)

        # Check if the image has changed
        # We alert on this as a secondary check for malicious images
        # https://docs.djangoproject.com/en/4.2/ref/forms/api/#django.forms.Form.changed_data
        if new_instance.image and "image" in self.changed_data:
            log.debug("Image field has changed: %s", new_instance.image.url)
            notify_on_ad_image_change.apply_async(args=[new_instance.pk])

        return new_instance

    class Meta:
        model = Advertisement
        fields = (
            "name",
            "live",
            "ad_types",
            "image",
            "link",
            "text",
            "headline",
            "content",
            "cta",
        )
        widgets = {
            "image": forms.FileInput(),
            "ad_types": forms.CheckboxSelectMultiple(),
        }


class AdvertisementCopyForm(forms.Form):

    """Used by advertisers to re-use their ads."""

    advertisements = AdvertisementMultipleChoiceField(
        queryset=Advertisement.objects.none(),
        required=False,
        help_text=_("Copy the following advertisements"),
    )

    def __init__(self, *args, **kwargs):
        """Add the form helper and customize the look of the form."""
        if "flight" in kwargs:
            self.flight = kwargs.pop("flight")
        else:
            raise RuntimeError("'flight' is required for the ad form")

        super().__init__(*args, **kwargs)

        self.fields["advertisements"].queryset = (
            Advertisement.objects.filter(flight__campaign=self.flight.campaign)
            .order_by("-flight__start_date", "slug")
            .select_related()
            .prefetch_related("ad_types")
        )

        self.helper = FormHelper()
        self.helper.attrs = {"id": "advertisements-copy"}

        self.helper.layout = Layout(
            Fieldset(
                "",
                Field(
                    "advertisements",
                    template="adserver/includes/widgets/advertisement-form-option.html",
                ),
                css_class="my-3",
            ),
            Submit("submit", _("Copy existing ads")),
        )

    def save(self):
        # Duplicate the advertisements into the new flight
        for ad in self.cleaned_data["advertisements"]:
            new_ad = ad.__copy__()
            new_ad.flight = self.flight
            new_ad.save()

        return len(self.cleaned_data["advertisements"])


class PublisherSettingsForm(forms.ModelForm):

    """Form for letting publishers control publisher specific settings."""

    def __init__(self, *args, **kwargs):
        """Add the form helper and customize the look of the form."""
        super().__init__(*args, **kwargs)

        if self.instance.stripe_connected_account_id:
            link_obj = stripe.Account.create_login_link(
                self.instance.stripe_connected_account_id
            )
            stripe_block = HTML(
                format_html(
                    "<a href='{}' target='_blank' class='btn btn-sm btn-outline-info mb-4'>"
                    "<span class='fa fa-cc-stripe fa-fw mr-2' aria-hidden='true'></span> {}"
                    "</a>",
                    link_obj.url,
                    gettext("Manage Stripe account"),
                )
            )
        elif settings.STRIPE_CONNECT_CLIENT_ID:
            connect_url = reverse(
                "publisher_stripe_oauth_connect", args=[self.instance.slug]
            )
            stripe_block = HTML(
                format_html(
                    "<a href='{}' target='_blank' class='btn btn-sm btn-outline-info mb-4'>"
                    "<span class='fa fa-cc-stripe fa-fw mr-2' aria-hidden='true'></span> {}"
                    "</a>",
                    connect_url,
                    gettext("Connect via Stripe"),
                )
            )
        else:
            stripe_block = HTML("<!-- Stripe is not configured -->")

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                _("Payout settings"),
                Field("payout_method", data_bind="value: payoutMethod"),
                Div(stripe_block, data_bind="visible: (payoutMethod() == 'stripe')"),
                Div(
                    PrependedText(
                        "open_collective_name", "https://opencollective.com/"
                    ),
                    data_bind="visible: (payoutMethod() == 'opencollective')",
                ),
                Div(
                    Field("paypal_email", placeholder="you@yourdomain.com"),
                    data_bind="visible: (payoutMethod() == 'paypal')",
                ),
                "skip_payouts",
                css_class="my-3",
            ),
            Fieldset(
                _("Control advertiser campaign types"),
                "allow_community_campaigns",
                "allow_house_campaigns",
                HTML(
                    "<p class='form-text small text-muted'>"
                    + str(
                        _(
                            "Use these checkboxes to control the types of advertiser campaigns "
                            "that are allowed on your site. "
                            "House campaigns are used when initially setting up your account."
                        )
                    )
                    + "</p>"
                ),
                css_class="my-3",
            ),
            Fieldset(
                _("Reporting settings"),
                "record_placements",
                HTML(
                    "<p class='form-text small text-muted'>"
                    + str(
                        _(
                            "Placements allow you to track ads on different parts of your site. "
                            "Any ad block with a `id` will be recorded, and you can view results based on the `id`."
                        )
                    )
                    + "</p>"
                ),
                css_class="my-3",
            ),
            Submit("submit", "Save settings"),
        )

    class Meta:
        model = Publisher
        fields = [
            "payout_method",
            "open_collective_name",
            "paypal_email",
            "skip_payouts",
            "allow_affiliate_campaigns",
            "allow_community_campaigns",
            "allow_house_campaigns",
            "record_placements",
            "record_placements",
        ]


class InviteUserForm(forms.ModelForm):

    """
    Used to invite users to collaborate on an advertiser/publisher.

    If the user already exists, the user will be returned from ``save()``
    without a duplicate being created.
    """

    def __init__(self, *args, **kwargs):
        """Add the form helper and customize the look of the form."""
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                "",
                Field("name"),
                Field("email", placeholder="user@yourdomain.com"),
                css_class="my-3",
            ),
            Submit("submit", "Send invite"),
        )

    def clean_email(self):
        email = self.cleaned_data.get("email")
        return User.objects.normalize_email(email)

    def get_existing_user(self):
        """Return an existing user with the email or None if no user exists."""
        email = self.cleaned_data["email"]
        return User.objects.filter(email=email).first()

    def validate_unique(self):
        """Remove the uniqueness check on email. Handle this in save()."""

    def save(self, commit=True):
        # Get the user if it already exists
        user = self.get_existing_user()
        if not user:
            # Invite the user if they're new
            user = super().save(commit)
            user.invite_user()

        # Track who added this user
        update_change_reason(user, "Invited via authorized users view")

        # You will need to add the user to the publisher/advertiser in the view
        return user

    class Meta:
        model = User
        fields = [
            "name",
            "email",
        ]


class AccountForm(forms.ModelForm):

    """Form used to update account information and notifications."""

    def __init__(self, *args, **kwargs):
        """Set up the form helper for the account."""
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                "",
                "name",
                css_class="my-3",
            ),
            Fieldset(
                _("Notification settings"),
                "notify_on_completed_flights",
                css_class="my-3",
            ),
            Submit("submit", _("Update account")),
        )

    class Meta:
        model = get_user_model()
        fields = ("name", "notify_on_completed_flights")


class SupportForm(forms.Form):

    """
    Form used to contact the support team.

    By default, this uses email but can be configured to submit to a remote URL
    for services that handle support (eg. Front).
    """

    subject = forms.CharField(max_length=255)
    body = forms.CharField(label=_("Message"), widget=forms.Textarea)

    # These are always populated from the request
    name = forms.CharField(widget=forms.HiddenInput)
    email = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        """Add the form helper and customize the look of the form."""
        self.request = kwargs.pop("request")  # Request is required

        if "initial" not in kwargs:
            kwargs["initial"] = {}
        kwargs["initial"].update(
            {
                "name": self.request.user.get_full_name(),
                "email": self.request.user.email,
                "subject": self.request.GET.get("subject", ""),
                "body": self.request.GET.get("body", ""),
            }
        )

        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        if settings.ADSERVER_SUPPORT_FORM_ACTION:
            # Set a custom form action - where the form submits to
            # This can be used to submit the form to an external help desk
            self.helper.form_action = settings.ADSERVER_SUPPORT_FORM_ACTION
            self.helper.disable_csrf = True
            self.helper.attrs = {
                "accept_charset": "utf-8",
                "enctype": "multipart/form-data",
            }

        self.helper.layout = Layout(
            Fieldset(
                "",
                Field("name"),
                Field("email"),
                Field("subject", placeholder=_("Your message subject")),
                Field("body", placeholder=_("Your message")),
                css_class="my-3",
            ),
            Submit("submit", _("Send support message")),
            HTML(
                "<p class='form-text small text-muted'>"
                + str(_("Typical turnaround time is 1-2 business days"))
                + "</p>"
            ),
        )

    def save(self):
        """Construct the message (with metadata) and send the support message."""
        to_email = settings.ADSERVER_SUPPORT_TO_EMAIL
        if not to_email:
            site = get_current_site(request=self.request)
            to_email = f"support@{site.domain}"
            log.warning(
                "Using the default support email address because ADSERVER_SUPPORT_TO_EMAIL is not configured"
            )

        subject = self.cleaned_data["subject"]
        body = self.cleaned_data["body"]

        # Even though the user name and email are submitted with the form,
        # always use the server value
        # Don't trust the POST data if you don't have to
        user = self.request.user

        email = EmailMessage(
            subject,
            render_to_string(
                "adserver/email/support-message.txt",
                {"subject": subject, "body": body, "user": user},
            ),
            settings.DEFAULT_FROM_EMAIL,
            [to_email],
            reply_to=[user.email],
        )
        email.send()
