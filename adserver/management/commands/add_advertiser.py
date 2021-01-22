"""
Add an advertiser to the DB and setup a campaign, user, and billing.

Sets up:

- The Advertiser record
- A default campaign record
- An initial flight with some reasonable defaults
- A user with access to the advertiser
- If Stripe is configured, setup a Stripe customer for the advertiser

This DOES NOT:

- Send the newly created user an invite to the platform
- Customize the targeting of the flight
- Customize CPC for CPC-based advertisers

Example::

   ./manage.py add_advertiser -e jfoo@bigco.com -n "John Foo" -a "Big Co."
"""
import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.core.validators import validate_email
from django.utils.text import slugify
from django.utils.translation import ugettext_lazy as _

from ...constants import PAID_CAMPAIGN
from ...models import Advertiser
from ...models import Campaign
from ...models import Flight
from ...models import PublisherGroup


User = get_user_model()


class Command(BaseCommand):

    """Add an advertiser from the command line."""

    DEFAULT_CPM = 3.33
    DEFAULT_NUM_IMPRESSIONS = 150000
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

    def add_arguments(self, parser):
        # These fields will prompt if not provided
        parser.add_argument(
            "-e", "--email", type=str, help=_("Email of user managing this advertiser")
        )
        parser.add_argument(
            "-n", "--name", type=str, help=_("Name of user managing this advertiser")
        )
        parser.add_argument(
            "-a", "--advertiser-name", type=str, help=_("Name of the advertiser")
        )

        # These use the defaults if not provided
        parser.add_argument(
            "--cpm",
            type=float,
            default=self.DEFAULT_CPM,
            help=_("CPM for the first flight [%s]" % self.DEFAULT_CPM),
        )
        parser.add_argument(
            "--num-impressions",
            type=int,
            default=self.DEFAULT_NUM_IMPRESSIONS,
            help=_(
                "Number of impressions for the first flight [%s]"
                % self.DEFAULT_NUM_IMPRESSIONS
            ),
        )

    def handle_user_creation(self):
        """Create a user account that will be connected to the advertiser."""
        email = self.kwargs["email"]
        name = self.kwargs["name"]

        while not email:
            email = input(_("Email of user managing this advertiser: "))
            try:
                validate_email(email)
            except ValidationError:
                self.stderr.write(self.style.ERROR(_("Invalid email")))
                email = None

        while not name:
            name = input(_("Name of user managing this advertiser: "))

        try:
            user = User.objects.create_user(name=name, email=email, password="")
            self.stdout.write(self.style.SUCCESS(_("Successfully created user")))
        except Exception as e:
            self.stderr.write(self.style.ERROR("User creation failed: %s" % e))
            user = User.objects.get(email=email)

        return user

    def handle_advertiser_creation(self):
        """Create an advertiser, campaign, and flight."""
        advertiser_name = self.kwargs["advertiser_name"]
        cpm = self.kwargs["cpm"]
        num_impressions = self.kwargs["num_impressions"]

        while not advertiser_name:
            advertiser_name = input(_("Name of the advertiser: "))
            if Advertiser.objects.filter(name=advertiser_name).exists():
                self.stderr.write(
                    self.style.ERROR(
                        _("Advertiser '%s' already exists" % advertiser_name)
                    )
                )
                advertiser_name = None

        advertiser = Advertiser.objects.create(
            name=advertiser_name, slug=slugify(advertiser_name)
        )
        self.stdout.write(self.style.SUCCESS(_("Successfully created advertiser")))

        campaign = Campaign.objects.create(
            advertiser=advertiser,
            name=advertiser_name,
            slug=slugify(advertiser_name),
            campaign_type=PAID_CAMPAIGN,
        )
        self.stdout.write(self.style.SUCCESS(_("Successfully created advertiser")))

        for pub_group in PublisherGroup.objects.all():
            campaign.publisher_groups.add(pub_group)

        flight_name = f"{advertiser_name} Initial"
        Flight.objects.create(
            campaign=campaign,
            name=flight_name,
            slug=slugify(flight_name),
            cpm=cpm,
            sold_impressions=num_impressions,
            targeting_parameters={
                "include_countries": self.DEFAULT_COUNTRY_TARGETING,
            },
        )
        self.stdout.write(self.style.SUCCESS(_("Successfully created flight")))

        return advertiser

    def handle_stripe_customer_creation(self, user, advertiser):
        """Setup a Stripe customer for this user."""
        if not settings.STRIPE_SECRET_KEY:
            self.stderr.write(
                self.style.ERROR(
                    _("Skipping Stripe customer setup since Stripe is not configured")
                )
            )
            return None

        stripe_customer = stripe.Customer.create(
            name=user.name,
            email=user.email,
            description=f"Advertising @ {advertiser.name}",
        )
        self.stdout.write(
            self.style.SUCCESS(_("SuccessSuccessfully created Stripe customer"))
        )
        return stripe_customer

    def handle(self, *args, **kwargs):
        self.kwargs = kwargs

        user = self.handle_user_creation()
        advertiser = self.handle_advertiser_creation()
        stripe_customer = self.handle_stripe_customer_creation(user, advertiser)

        # Attach Stripe customer record to the advertiser
        if stripe_customer:
            advertiser.stripe_customer_id = stripe_customer.id
            advertiser.save()

        user.advertisers.add(advertiser)
