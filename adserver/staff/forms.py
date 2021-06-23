"""Views for the administrator actions."""
import logging

import requests
import stripe
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field
from crispy_forms.layout import Fieldset
from crispy_forms.layout import HTML
from crispy_forms.layout import Layout
from crispy_forms.layout import Submit
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import ugettext_lazy as _
from simple_history.utils import update_change_reason

from ..constants import EMAILED
from ..models import Advertiser
from ..models import Campaign
from ..models import Flight
from ..models import Publisher
from ..models import PublisherGroup

log = logging.getLogger(__name__)  # noqa

User = get_user_model()


class CreateAdvertiserForm(forms.Form):

    """
    Creates an advertiser.

    This isn't a simple model form because it creates a few additional objects as well
    such as a user (needed to create a stripe account), campaign, and initial flight.
    """

    # TODO: Make these configurable in the web UI as a dropdown of common values.
    DEFAULT_CPM = 3.33
    DEFAULT_NUM_IMPRESSIONS = 300000
    DEFAULT_COUNTRY_TARGETING = [
        # North America
        "US",
        "CA",
        # Core Europe
        "DE",
        "GB",
        "FR",
        "IT",
        "ES",
        "CH",
        "NL",
        "PT",
        "AT",
        "BE",
        "IE",
        "GR",
        "SE",
        "DK",
        "NO",
        "FI",
        # Bundled into Europe
        "IL",
        # Australia and New Zealand
        "AU",
        "NZ",
    ]

    # Advertiser information
    advertiser_name = forms.CharField(label=_("Advertiser name"), max_length=200)

    # User information
    user_name = forms.CharField(label=_("Name"), max_length=200)
    user_email = forms.EmailField(label=_("Email"))

    # Used to track historical changes
    message = "Added via staff interface"

    def __init__(self, *args, **kwargs):
        """Add the form helper and customize the look of the form."""
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()

        self.helper.layout = Layout(
            Fieldset(
                _("Advertiser information"),
                Field("advertiser_name", placeholder=_("Company name")),
                css_class="my-3",
            ),
            Fieldset(
                _("Managing user"),
                Field("user_name"),
                Field("user_email", placeholder="advertiser@company.com"),
                css_class="my-3",
            ),
            Submit("submit", _("Create advertiser")),
            HTML(
                "<p class='form-text small text-muted'>"
                + str(
                    _(
                        "Creates an advertiser, a campaign, user account, and initial flight. "
                        "The user will receive an invitation email."
                    )
                )
                + "</p>"
            ),
        )

    def clean_advertiser_name(self):
        advertiser_name = self.cleaned_data["advertiser_name"].strip()

        if Advertiser.objects.filter(name=advertiser_name).exists():
            raise forms.ValidationError(_("Advertiser already exists"))

        return advertiser_name

    def create_user(self):
        """Create the user account and send an invite email."""
        user_name = self.cleaned_data["user_name"].strip()
        user_email = self.cleaned_data["user_email"]
        user = User.objects.create_user(name=user_name, email=user_email, password="")
        update_change_reason(user, self.message)
        if hasattr(user, "invite_user"):
            user.invite_user()
        return user

    def create_advertiser(self):
        """Create the advertiser, campaign, and initial flight."""
        advertiser_name = self.cleaned_data["advertiser_name"].strip()

        advertiser = Advertiser.objects.create(
            name=advertiser_name, slug=slugify(advertiser_name)
        )
        campaign = Campaign.objects.create(
            advertiser=advertiser,
            name=advertiser_name,
            slug=slugify(advertiser_name),
        )
        for pub_group in PublisherGroup.objects.all():
            campaign.publisher_groups.add(pub_group)

        flight_name = f"{advertiser_name} Initial Flight"
        flight = Flight.objects.create(
            campaign=campaign,
            name=flight_name,
            slug=slugify(flight_name),
            cpm=self.DEFAULT_CPM,
            sold_impressions=self.DEFAULT_NUM_IMPRESSIONS,
            targeting_parameters={
                "include_countries": self.DEFAULT_COUNTRY_TARGETING,
            },
        )

        update_change_reason(advertiser, self.message)
        update_change_reason(campaign, self.message)
        update_change_reason(flight, self.message)

        return advertiser

    def create_stripe_customer(self, user, advertiser):
        """Setup a Stripe customer for this user."""
        if not settings.STRIPE_SECRET_KEY:
            return None

        stripe_customer = stripe.Customer.create(
            name=user.name,
            email=user.email,
            description=f"Advertising @ {advertiser.name}",
        )
        return stripe_customer

    def save(self):
        """Create the advertiser and associated objects. Send the invitation to the user account."""
        advertiser = self.create_advertiser()
        user = self.create_user()

        if settings.STRIPE_SECRET_KEY:
            # Attach Stripe customer record to the advertiser
            stripe_customer = self.create_stripe_customer(user, advertiser)
            advertiser.stripe_customer_id = stripe_customer.id
            advertiser.save()

        user.advertisers.add(advertiser)

        return advertiser


class CreatePublisherForm(forms.Form):

    """
    Creates a publisher.

    This isn't a simple model form because it creates a few additional objects as well
    """

    DEFAULT_GROUP = "ethicalads-network"

    # Advertiser information
    site = forms.CharField(label=_("Publisher site"), max_length=200)

    # User information
    user_name = forms.CharField(label=_("User Name"), max_length=200)
    user_email = forms.EmailField(label=_("User Email"))

    # Publisher Info
    keywords = forms.CharField(
        label=_("Default Keywords"), max_length=200, required=False
    )

    # Used to track historical changes
    message = "Added via staff interface"

    def __init__(self, *args, **kwargs):
        """Add the form helper and customize the look of the form."""
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()

        self.helper.layout = Layout(
            Fieldset(
                _("Publisher information"),
                Field("site", placeholder=_("example.com")),
                Field("keywords", placeholder=_("frontend,javascript,gaming")),
                css_class="my-3",
            ),
            Fieldset(
                _("Managing user"),
                Field("user_name"),
                Field("user_email", placeholder="publisher@email.com"),
                css_class="my-3",
            ),
            Submit("submit", _("Create publisher")),
            HTML(
                "<p class='form-text small text-muted'>"
                + str(_("Creates a publisher and sends user an invitation email."))
                + "</p>"
            ),
        )

    def clean_name(self):
        name = self.cleaned_data["name"].strip()

        if Publisher.objects.filter(name=name).exists():
            raise forms.ValidationError(_("Publisher already exists"))

        return name

    def create_user(self):
        """Create the user account and send an invite email."""
        user_name = self.cleaned_data["user_name"].strip()
        user_email = self.cleaned_data["user_email"]
        user = User.objects.create_user(name=user_name, email=user_email, password="")
        update_change_reason(user, self.message)
        if hasattr(user, "invite_user"):
            user.invite_user()
        return user

    def create_publisher(self):
        """Create the publisher."""
        site = self.cleaned_data["site"].strip()
        keywords = self.cleaned_data["keywords"].strip()

        publisher = Publisher.objects.create(
            name=site,
            slug=slugify(site),
            default_keywords=keywords,
        )

        # TODO: Allow configuring of publisher groups in form
        group_obj = PublisherGroup.objects.filter(slug=self.DEFAULT_GROUP).first()
        if group_obj:
            group_obj.publishers.add(publisher)

        update_change_reason(publisher, self.message)

        return publisher

    def save(self):
        """Create the publisher and associated objects. Send the invitation to the user account."""
        publisher = self.create_publisher()
        user = self.create_user()
        user.publishers.add(publisher)

        return publisher


class StartPublisherPayoutForm(forms.Form):

    """Start a publisher payout with an email."""

    # Advertiser information
    sender = forms.CharField(label=_("Sender"), max_length=200)
    subject = forms.CharField(label=_("Subject"), max_length=200)
    body = forms.CharField(label=_("body"), widget=forms.Textarea)
    amount = forms.CharField(label=_("Amount"), disabled=True)
    archive = forms.BooleanField(
        label=_("Archive after sending?"), initial=True, required=False
    )
    draft = forms.BooleanField(label=_("Create draft, don't send."), required=False)

    def __init__(self, *args, **kwargs):
        """Add the form helper and customize the look of the form."""
        self.publisher = kwargs.pop("publisher")
        self.amount = kwargs.pop("amount")
        self.start_date = kwargs.pop("start_date")
        self.end_date = kwargs.pop("end_date")
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.add_input(Submit("submit", "Send email"))

    def _send_email(self):
        token = getattr(settings, "FRONT_TOKEN")
        channel = getattr(settings, "FRONT_CHANNEL")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "to": [user.email for user in self.publisher.user_set.all()],
            "sender_name": self.cleaned_data["sender"],
            "subject": self.cleaned_data["subject"],
            "options": {"archive": self.cleaned_data["archive"]},
            "body": self.cleaned_data["body"],
        }

        url = f"https://api2.frontapp.com/channels/{channel}/messages"
        if self.cleaned_data["draft"]:
            url = f"https://api2.frontapp.com/channels/{channel}/drafts"
            # Allow the team to see the draft
            payload["mode"] = "shared"
            # Author is required on drafts..
            payload["author_id"] = getattr(settings, "FRONT_AUTHOR")

        log.info(
            "Sending email draft=%s archive=%s",
            self.cleaned_data["draft"],
            self.cleaned_data["archive"],
        )
        response = requests.request("POST", url, json=payload, headers=headers)
        log.info("Response: %s", response.status_code)

    def save(self):
        """Do the work to save the payout."""
        self._send_email()

        payout = self.publisher.payouts.create(
            date=timezone.now(),
            method=self.publisher.payout_method,
            amount=self.amount,
            start_date=self.start_date,
            end_date=self.end_date,
            status=EMAILED,
        )

        update_change_reason(payout, "Payout via staff interface")

        return payout
