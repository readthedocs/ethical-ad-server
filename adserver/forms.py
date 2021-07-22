"""Forms for the ad server."""
import logging

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
from django.utils.crypto import get_random_string
from django.utils.html import format_html
from django.utils.text import slugify
from django.utils.translation import ugettext
from django.utils.translation import ugettext_lazy as _
from simple_history.utils import update_change_reason

from .models import Advertisement
from .models import Flight
from .models import Publisher
from .regiontopics import africa
from .regiontopics import backend_web
from .regiontopics import data_science
from .regiontopics import devops
from .regiontopics import eu_aus_nz
from .regiontopics import exclude
from .regiontopics import frontend_web
from .regiontopics import latin_america
from .regiontopics import python
from .regiontopics import security_privacy
from .regiontopics import us_ca
from .regiontopics import wider_apac
from .validators import TargetingParametersValidator


log = logging.getLogger(__name__)  # noqa
User = get_user_model()


class FlightMixin:

    """Ensure the flight can't have both CPC and CPM."""

    def clean(self):
        cleaned_data = super().clean()
        cpc = cleaned_data.get("cpc")
        cpm = cleaned_data.get("cpm")
        if cpc > 0 and cpm > 0:
            raise forms.ValidationError(_("A flight cannot have both CPC & CPM"))

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
            "live",
            "priority_multiplier",
            "cpc",
            "sold_clicks",
            "cpm",
            "sold_impressions",
            "targeting_parameters",
        )


class FlightForm(FlightMixin, forms.ModelForm):

    """The form for flights used in a staff interface."""

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

        if self.instance.pk:
            self.fields["include_countries"].initial = ", ".join(
                self.instance.included_countries
            )
            self.fields["exclude_countries"].initial = ", ".join(
                self.instance.excluded_countries
            )
            self.fields["include_keywords"].initial = ", ".join(
                self.instance.included_keywords
            )

        self.helper = FormHelper()

        self.helper.layout = Layout(
            Fieldset(
                "",
                Div(
                    Div("start_date", css_class="form-group col-lg-6"),
                    Div("end_date", css_class="form-group col-lg-6"),
                    css_class="form-row",
                ),
                "live",
                css_class="my-3",
            ),
            Fieldset(
                _("Per impression (CPM) flights"),
                Div(
                    Div("cpm", css_class="form-group col-lg-6"),
                    Div("sold_impressions", css_class="form-group col-lg-6"),
                    css_class="form-row",
                ),
                css_class="my-3",
            ),
            Fieldset(
                _("Per click (CPC) flights"),
                Div(
                    Div("cpc", css_class="form-group col-lg-6"),
                    Div("sold_clicks", css_class="form-group col-lg-6"),
                    css_class="form-row",
                ),
                css_class="my-3",
            ),
            Fieldset(
                _("Flight targeting"),
                Div(
                    "include_countries",
                    Div(
                        HTML(
                            format_html(
                                """
                                <ul class="list-inline">
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_include_countries">US / Canada</a></li>
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_include_countries">EU / AU / NZ</a></li>
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_include_countries">APAC</a></li>
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_include_countries">Latin America</a></li>
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_include_countries">Africa</a></li>
                                </ul>
                            """,
                                ", ".join(us_ca),
                                ", ".join(eu_aus_nz),
                                ", ".join(wider_apac),
                                ", ".join(latin_america),
                                ", ".join(africa),
                            )
                        ),
                        css_class="small",
                    ),
                ),
                Div(
                    "exclude_countries",
                    Div(
                        HTML(
                            format_html(
                                """
                                <ul class="list-inline">
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_exclude_countries">US / Canada</a></li>
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_exclude_countries">EU / AU / NZ</a></li>
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_exclude_countries">APAC</a></li>
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_exclude_countries">Latin America</a></li>
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_exclude_countries">Africa</a></li>
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_exclude_countries">Exclude</a></li>
                                </ul>
                            """,
                                ", ".join(us_ca),
                                ", ".join(eu_aus_nz),
                                ", ".join(wider_apac),
                                ", ".join(latin_america),
                                ", ".join(africa),
                                ", ".join(exclude),
                            )
                        ),
                        css_class="small",
                    ),
                ),
                Div(
                    "include_keywords",
                    Div(
                        HTML(
                            format_html(
                                """
                                <ul class="list-inline">
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_include_keywords">data science/machine learning</a></li>
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_include_keywords">security/privacy</a></li>
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_include_keywords">devops</a></li>
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_include_keywords">frontend</a></li>
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_include_keywords">backend</a></li>
                                    <li class="list-inline-item"><a class="ea-update-field" href="#" data-value="{}" data-target-field="#id_include_keywords">python</a></li>
                                </ul>
                            """,
                                ", ".join(data_science),
                                ", ".join(security_privacy),
                                ", ".join(devops),
                                ", ".join(frontend_web),
                                ", ".join(backend_web),
                                ", ".join(python),
                            )
                        ),
                        css_class="small",
                    ),
                ),
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
        data = self.cleaned_data["include_keywords"]
        include_keywords = [kw.strip() for kw in data.split(",") if len(kw.strip()) > 0]
        if include_keywords:
            TargetingParametersValidator()({"include_keywords": include_keywords})
        return data

    def save(self, commit=True):
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
        if not self.instance.targeting_parameters["include_countries"]:
            del self.instance.targeting_parameters["include_countries"]
        if not self.instance.targeting_parameters["exclude_countries"]:
            del self.instance.targeting_parameters["exclude_countries"]
        if not self.instance.targeting_parameters["include_keywords"]:
            del self.instance.targeting_parameters["include_keywords"]

        return super().save(commit)

    class Meta:
        model = Flight

        fields = (
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
            ad_display_fields = ["headline", "content", "cta"]
        else:
            del self.fields["headline"]
            del self.fields["content"]
            del self.fields["cta"]
            self.fields["text"].widget.attrs["rows"] = 3
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
                *ad_display_fields,
                css_class="my-3",
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
        return super().save(commit)

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
                    "<a href='{}' target='_blank' class='btn btn-sm btn-outline-info'>"
                    "<span class='fa fa-cc-stripe fa-fw mr-2' aria-hidden='true'></span> {}"
                    "</a>",
                    link_obj.url,
                    ugettext("Manage Stripe account"),
                )
            )
        elif settings.STRIPE_CONNECT_CLIENT_ID:
            connect_url = reverse(
                "publisher_stripe_oauth_connect", args=[self.instance.slug]
            )
            stripe_block = HTML(
                format_html(
                    "<a href='{}' target='_blank' class='btn btn-sm btn-outline-info'>"
                    "<span class='fa fa-cc-stripe fa-fw mr-2' aria-hidden='true'></span> {}"
                    "</a>",
                    connect_url,
                    ugettext("Connect via Stripe"),
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
            "allow_affiliate_campaigns",
            "allow_community_campaigns",
            "allow_house_campaigns",
            "record_placements",
        ]


class InviteUserForm(forms.ModelForm):

    """Used to invite users to collaborate on an advertiser/publisher."""

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

    def save(self, commit=True):
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
