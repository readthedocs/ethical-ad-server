"""Forms for the ad server."""

import csv
import logging
from datetime import timedelta
from io import BytesIO
from io import TextIOWrapper

import bleach
import requests
import stripe
from allauth.mfa.utils import is_mfa_enabled
from crispy_forms.bootstrap import PrependedText
from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML
from crispy_forms.layout import Div
from crispy_forms.layout import Field
from crispy_forms.layout import Fieldset
from crispy_forms.layout import Layout
from crispy_forms.layout import Submit
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.shortcuts import get_current_site
from django.core.exceptions import ValidationError
from django.core.files.images import get_image_dimensions
from django.core.files.storage import default_storage
from django.core.mail import EmailMessage
from django.core.validators import URLValidator
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.html import format_html
from django.utils.text import slugify
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from .auth.models import UserAdvertiserMember
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
            "daily_cap",
            "targeting_parameters",
            "traffic_fill",
            "traffic_cap",
            "discount",
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
    budget = forms.FloatField(
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

        self.fields["include_regions"].widget.attrs["data-bind"] = "checked: regions"
        self.fields["include_topics"].widget.attrs["data-bind"] = "checked: topics"

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
                Div(
                    Div("live", css_class="form-group col-lg-6"),
                    Div("auto_renew", css_class="form-group col-lg-6"),
                    css_class="form-row",
                ),
                Div(
                    PrependedText(
                        "budget",
                        "$",
                        min=0,
                        step="0.01",
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
            # NOTE: remove these when this form is made for non-staff users
            Field("discount"),
            Field("priority_multiplier"),
            Fieldset(
                _("Flight targeting"),
                HTML(
                    "<p class='form-text'>"
                    + str(_("Standard CPM: "))
                    + "<span id='estimated-cpm' data-bind='text: estimatedCpm()'></span> "
                    + "<span data-bind='if: budget() >= 2990 && budget() < 24990'>(10% discount)</span>"
                    + "<span data-bind='if: budget() > 24990'>(15% discount)</span>"
                    + "</p>"
                ),
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
            "auto_renew",
            "cpc",
            "sold_clicks",
            "cpm",
            "sold_impressions",
            "discount",
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


class FlightAutoRenewForm(forms.ModelForm):
    """Allow customers to set a flight to automatically renew or not."""

    def __init__(self, *args, **kwargs):
        """Set the flight form helper and initial data."""
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.attrs = {"id": "flight-autorenew-form"}

        self.helper.layout = Layout(
            Fieldset(
                "",
                Field("auto_renew"),
                Field("auto_renew_payment_method"),
                css_class="my-3",
            ),
            Submit("submit", _("Update flight auto-renewal")),
            HTML(
                "<p class='form-text small text-muted'>"
                + str(
                    _(
                        "Your account manager will be notified and will adjust pricing if necessary."
                    )
                )
                + "</p>"
            ),
        )

    class Meta:
        model = Flight

        fields = ("auto_renew", "auto_renew_payment_method")


class FlightRenewForm(FlightMixin, FlightCreateForm):
    """Form class for creating a new flight via renewal."""

    advertisements = AdvertisementMultipleChoiceField(
        queryset=Advertisement.objects.none(),
        required=False,
        help_text=_("Renew the flight with the following advertisements"),
    )
    budget = forms.FloatField(
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
                Div(
                    Div("live", css_class="form-group col-lg-6"),
                    Div("auto_renew", css_class="form-group col-lg-6"),
                    css_class="form-row",
                ),
                Div(
                    PrependedText(
                        "budget",
                        "$",
                        min=0,
                        step="0.01",
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
        for field in (
            "targeting_parameters",
            "priority_multiplier",
            "traffic_cap",
            "discount",
        ):
            setattr(instance, field, getattr(self.old_flight, field))
        instance.save()

        # Duplicate the advertisements into the new flight
        for ad in self.cleaned_data["advertisements"]:
            new_ad = ad.__copy__()
            new_ad.flight = instance
            new_ad.live = True
            new_ad.save()  # Automatically gets a new slug

        # If the old flight was niche targeted, target the new flight to the same URLs
        instance.copy_niche_targeting_urls(self.old_flight)

        return instance

    class Meta:
        model = Flight

        fields = (
            "name",
            "campaign",
            "start_date",
            "end_date",
            "live",
            "auto_renew",
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

    budget = forms.FloatField(
        label=_("Budget"),
    )

    regions = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    topics = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple(),
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
                "regions": self.old_flight.targeting_parameters.get(
                    "include_regions", []
                )
                if self.old_flight and self.old_flight.targeting_parameters
                else [],
                "topics": self.old_flight.targeting_parameters.get("include_topics", [])
                if self.old_flight and self.old_flight.targeting_parameters
                else [],
            }
        )

        # Sets self.advertiser
        super().__init__(*args, **kwargs)

        self.fields["budget"].widget.attrs["data-bind"] = "textInput: budget"
        self.fields["regions"].widget.attrs["data-bind"] = "checked: regions"
        self.fields["topics"].widget.attrs["data-bind"] = "checked: topics"
        self.fields["note"].widget.attrs["rows"] = 3
        self.fields["note"].help_text = _(
            "Do you have any changes you'd like to make from previous flights or any special instructions?"
        )
        self.fields["start_date"].help_text = _("The target start date for this flight")
        self.fields["end_date"].help_text = _(
            "The target end date for this flight (it may go after this date)"
        )
        self.fields["auto_renew"].help_text = _(
            "Flights that automatically renew receive an additional 10% discount"
        )
        self.fields["advertisements"].queryset = (
            self.old_flight.advertisements.all()
            if self.old_flight
            else Advertisement.objects.none()
        )

        self.fields["regions"].choices = [
            (r.slug, r.name)
            for r in Region.objects.filter(selectable=True).order_by("order", "slug")
        ]
        self.fields["topics"].choices = [
            (t.slug, t.name)
            for t in Topic.objects.filter(selectable=True).order_by("slug")
        ]

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
                Field("auto_renew"),
                Div(
                    PrependedText(
                        "budget",
                        "$",
                        min=0,
                        step="0.01",
                        data_bind="textInput: budget",
                    ),
                ),
                css_class="my-3",
            ),
            Fieldset(
                _("Flight targeting"),
                HTML(
                    "<p class='form-text mb-0'>"
                    + str(_("Estimated CPM: "))
                    + "<span id='estimated-cpm' data-bind='text: estimatedCpm()'></span> "
                    + "<span data-bind='if: budget() >= 2990 && budget() < 24990'>(10% discount applied)</span>"
                    + "<span data-bind='if: budget() > 24990'>(15% discount applied)</span>"
                    + "</p>"
                    + "<p class='form-text small text-muted'>"
                    + str(
                        _(
                            "Your account manager will confirm your campaign's rate before it starts."
                        )
                    )
                    + "</p>"
                ),
                Div(
                    Div(
                        Field("regions"),
                        css_class="form-group col-lg-6",
                    ),
                    Div(
                        Field("topics"),
                        css_class="form-group col-lg-6",
                    ),
                    css_class="form-row",
                ),
                HTML(
                    "<p class='form-text small text-muted'>"
                    + str(
                        _(
                            "If you need more fine targeting than these options and it's different from any previous flights you've run, "
                            "please let your account manager know in the 'note' field below."
                        )
                    )
                    + "</p>"
                ),
                css_class="my-3",
            ),
            Field("note"),
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

        if not self.instance.targeting_parameters:
            # This can happen if the flight was setup with no targeting at all
            self.instance.targeting_parameters = {}

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

        # Set the regions and/or topics they set in the form
        if self.cleaned_data["regions"]:
            self.instance.targeting_parameters["include_regions"] = self.cleaned_data[
                "regions"
            ]
        if self.cleaned_data["topics"]:
            self.instance.targeting_parameters["include_topics"] = self.cleaned_data[
                "topics"
            ]

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
            "auto_renew",
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

            if ad_type.has_image and image:
                width, height = get_image_dimensions(image)

                if not ad_type.validate_image(image):
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

                if not ad_type.validate_text(stripped_text):
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

        # Get the lowest maximum text length across all eligible ad types
        ad_type_max_lengths = [at.max_text_length for at in adtype_queryset] or [0]
        maximum_text_length = min(ad_type_max_lengths)

        # Get the width/height of any ad types (if applicable)
        ad_type_image_width = (
            [at.image_width for at in adtype_queryset if at.image_width] or [0]
        )[0]
        ad_type_image_height = (
            [at.image_height for at in adtype_queryset if at.image_height] or [0]
        )[0]

        self.fields["image"].help_text = _(
            "Sized according to the ad type. Need help with manipulating or resizing images? We can <a href='%s'>help</a>."
        ) % (reverse("support") + "?subject=Image+help")

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
                Field(
                    "image",
                    data_width=ad_type_image_width,
                    data_height=ad_type_image_height,
                ),
                css_class="my-3",
            ),
            Fieldset(
                _("Advertisement text"),
                Div(
                    HTML(
                        f"<span data-bind='text: totalLength()'></span> / <span data-bind='text: maxLength()' id='id_maximum_text_length' data-maximum-length='{maximum_text_length}'></span> characters"
                    ),
                    # Only display on "new style" ads with the headline, content, and CTA
                    # Simply hide it on the old style ads.
                    data_bind="visible: totalLength() > 0, css: totalLength() > maxLength() ? 'text-danger' : 'text-muted'",
                    css_class="small mb-2",
                ),
                *ad_display_fields,
            ),
            Submit("submit", _("Save advertisement")),
        )

    def save(self, commit=True):
        if not self.instance.flight_id:
            self.instance.flight = self.flight
        if not self.instance.slug:
            # Only needed on create
            self.instance.slug = Advertisement.generate_slug(self.instance.name)

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


class BulkAdvertisementUploadCSVForm(forms.Form):
    """
    Used by advertisers to upload ads in bulk.

    The actual saving of bulk ads is done by the BulkAdvertisementPreviewForm.
    """

    REQUIRED_FIELD_NAMES = [
        "Name",
        "Live",
        "Link URL",
        "Image URL",
        "Headline",
        "Content",
        "Call to Action",
    ]

    advertisements = forms.FileField(
        label=_("Advertisements"), help_text=_("Upload a CSV using our ad template")
    )

    def __init__(self, *args, **kwargs):
        """Add the form helper and customize the look of the form."""
        if "flight" in kwargs:
            self.flight = kwargs.pop("flight")
        else:
            raise RuntimeError("'flight' is required for the bulk ad form")

        super().__init__(*args, **kwargs)

        self.fields["advertisements"].widget.attrs["accept"] = "text/csv"

        self.helper = FormHelper()
        self.helper.attrs = {
            "id": "advertisements-bulk-upload",
            "enctype": "multipart/form-data",
        }

        self.helper.layout = Layout(
            Fieldset(
                "",
                Field("advertisements", placeholder="Upload a CSV file"),
                css_class="my-3",
            ),
            Submit("submit", _("Preview ads")),
        )

    def clean_advertisements(self):
        """Verify the CSV can be opened and has all the right fields."""
        csvfile = self.cleaned_data["advertisements"]
        try:
            reader = csv.DictReader(
                TextIOWrapper(csvfile, encoding="utf-8", newline="")
            )
        except Exception:
            raise forms.ValidationError(_("Could not open the CSV file."))

        for fieldname in self.REQUIRED_FIELD_NAMES:
            if fieldname not in reader.fieldnames:
                raise forms.ValidationError(
                    _("Missing required field %(fieldname)s."),
                    params={"fieldname": fieldname},
                )

        ads = []
        url_validator = URLValidator(schemes=("http", "https"))
        for row in reader:
            image_url = row["Image URL"].strip()
            link_url = row["Link URL"].strip()
            name = row["Name"].strip()
            headline = row["Headline"].strip()
            content = row["Content"].strip()
            cta = row["Call to Action"].strip()

            for url in (image_url, link_url):
                try:
                    url_validator(url)
                except ValidationError:
                    raise forms.ValidationError(
                        _("'%(url)s' is an invalid URL."), params={"url": url}
                    )

            image_resp = None
            try:
                image_resp = requests.get(image_url, timeout=3, stream=True)
            except Exception:
                pass

            if not image_resp or not image_resp.ok:
                raise forms.ValidationError(
                    _("Could not retrieve image '%(image)s'."),
                    params={"image": image_url},
                )

            image = BytesIO(image_resp.raw.read())
            width, height = get_image_dimensions(image)

            if width is None or height is None:
                raise forms.ValidationError(
                    _("Image for %(name)s isn't a valid image"),
                    params={
                        "name": name,
                    },
                )

            ad_text = f"{headline}{content}{cta}"

            for ad_type in self.flight.campaign.allowed_ad_types(
                exclude_deprecated=True
            ):
                if not ad_type.validate_text(ad_text):
                    raise forms.ValidationError(
                        _(
                            "Total text for '%(ad)s' must be %(max_chars)s or less (it is %(text_len)s)"
                        ),
                        params={
                            "ad": name,
                            "max_chars": ad_type.max_text_length,
                            "text_len": len(ad_text),
                        },
                    )

                if not ad_type.validate_image(image):
                    raise forms.ValidationError(
                        _(
                            "Images must be %(required_width)s * %(required_height)s "
                            "(for %(name)s it is %(width)s * %(height)s)"
                        ),
                        params={
                            "name": name,
                            "required_width": ad_type.image_width,
                            "required_height": ad_type.image_height,
                            "width": width,
                            "height": height,
                        },
                    )

            image_name = image_url[image_url.rfind("/") + 1 :]
            image_path = f"images/{timezone.now():%Y}/{timezone.now():%m}/{image_name}"
            default_storage.save(image_path, image)

            ads.append(
                {
                    "name": name,
                    "image_path": image_path,
                    "image_name": image_name,
                    "image_url": default_storage.url(image_path),
                    "live": row["Live"].strip().lower() == "true",
                    "link": link_url,
                    "headline": headline,
                    "content": content,
                    "cta": cta,
                }
            )

        return ads

    def get_ads(self):
        if not self.is_valid():
            raise RuntimeError("Form must be valid and bound to get the ads")

        return self.cleaned_data["advertisements"]


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
                Div(
                    PrependedText(
                        "github_sponsors_name",
                        "https://github.com/sponsors/",
                        placeholder="your-github-name",
                    ),
                    data_bind="visible: (payoutMethod() == 'github')",
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
            "github_sponsors_name",
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

    role = forms.ChoiceField(
        required=True,
        # This form works for both publishers and advertisers
        # Currently, the roles are the same for both
        # If that ever changes, this will need an update
        choices=((r, r) for r in UserAdvertiserMember.ROLES),
    )

    def __init__(self, *args, **kwargs):
        """Add the form helper and customize the look of the form."""
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                "",
                Field("name"),
                Field("email", placeholder="user@yourdomain.com"),
                Field("role"),
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
            # See: https://github.com/jazzband/django-simple-history/issues/1181
            # update_change_reason(user, "Invited via authorized users view")

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
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                "",
                "name",
                HTML(
                    render_to_string(
                        "adserver/accounts/includes/2fa-account-form.html",
                        {"mfa_enabled": is_mfa_enabled(self.request.user)},
                    )
                ),
                css_class="my-3",
            ),
            Fieldset(
                _("Notification settings"),
                "flight_notifications",
                css_class="my-3",
            ),
            Submit("submit", _("Update account")),
        )

    class Meta:
        model = get_user_model()
        fields = ("name", "flight_notifications")


class SupportForm(forms.Form):
    """
    Form used to contact the support team.

    By default, this uses email but can be configured to submit to a remote URL
    for services that handle support (eg. Front).
    """

    subject = forms.CharField(max_length=255)
    body = forms.CharField(label=_("Message"), widget=forms.Textarea)
    upload = forms.FileField(
        required=False,
        help_text=_(
            "If there's a file that helps explain this support request, please attach it."
        ),
    )

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
        self.helper.attrs = {
            "accept_charset": "utf-8",
            "enctype": "multipart/form-data",
        }

        if settings.ADSERVER_SUPPORT_FORM_ACTION:
            # Set a custom form action - where the form submits to
            # This can be used to submit the form to an external help desk
            self.helper.form_action = settings.ADSERVER_SUPPORT_FORM_ACTION
            self.helper.disable_csrf = True

        self.helper.layout = Layout(
            Fieldset(
                "",
                Field("name"),
                Field("email"),
                Field("subject", placeholder=_("Your message subject")),
                Field("body", placeholder=_("Your message")),
                Field("upload"),
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
        upload = self.cleaned_data["upload"]

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

        if upload:
            # https://docs.djangoproject.com/en/4.2/ref/files/uploads/#django.core.files.uploadedfile.UploadedFile
            # https://docs.djangoproject.com/en/4.2/topics/email/#emailmessage-objects
            # This is a potential issue if somebody uploads a very large file as it will read it into memory.
            email.attach(upload.name, upload.read(), upload.content_type)

        email.send()
