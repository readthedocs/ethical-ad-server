"""Ad decision backends"""
import logging
import random

from django.db import models

from ..constants import COMMUNITY_CAMPAIGN
from ..constants import HOUSE_CAMPAIGN
from ..constants import PAID_CAMPAIGN
from ..models import AdImpression
from ..models import Advertisement
from ..models import Campaign
from ..models import Flight
from ..utils import get_ad_day

log = logging.getLogger(__name__)


class BaseAdDecisionBackend:

    """A base decision backend -- other decision backends should extend this"""

    def __init__(self, request, placements, publisher, **kwargs):
        """
        Initialize an ad decision based on the request data

        :param request: the HttpRequest object with geo data attached from GeolocationMiddleware
        :param placements: possible positions for the ad to go
        :param kwargs: Any additional possible arguments for the backend
        """
        self.request = request
        self.placements = placements
        self.publisher = publisher

        self.country_code = request.geo.country_code
        self.region_code = request.geo.region_code
        self.metro_code = request.geo.metro_code

        # Optional parameters
        self.keywords = kwargs.get("keywords", []) or []
        self.campaign_types = kwargs.get("campaign_types", []) or []

        if not self.campaign_types:
            # Unless specified, ads from any campaign type can be shown
            self.campaign_types = [HOUSE_CAMPAIGN, COMMUNITY_CAMPAIGN, PAID_CAMPAIGN]

        # When set, only return a specific ad or ads from a campaign
        self.ad_slug = kwargs.get("ad_slug")
        self.campaign_slug = kwargs.get("campaign_slug")

    def get_ad_and_placement(self):
        """
        Choose an ad to display

        This is the main entry point for making an ad decision. It makes the decision
        based on the passed information including the request, the available places
        for an ad (placements), and any other data passed to the backend.

        ::

            backend = BaseAdDecisionBackendSubclass(request, placements)
            ad, placement = backend.get_ad_and_placement()

            if ad and placement
                # ...  # there could be no matching ads

        :return: A 2-tuple of the `Advertisement` object and the matching `placement`
        """
        raise NotImplementedError(
            "subclasses of BaseAdDecisionBackend must override get_ad_and_placement()"
        )

    def get_placement(self, advertisement):
        """Gets the first matching placement for a given ad"""
        if not advertisement.ad_type:
            return None

        for placement in self.placements:
            # A placement "matches" if the ad type matches
            # If the ad or campaign is specified, they must also match
            if (
                placement["ad_type"] == advertisement.ad_type.slug
                and (not self.ad_slug or advertisement.slug == self.ad_slug)
                and (
                    not self.campaign_slug
                    or advertisement.flight.campaign.slug == self.campaign_slug
                )
            ):
                return placement

        return None

    def should_display_ads(self):
        """Whether to not display ads based on the user, request, or other settings"""
        return True

    def get_ads_queryset(self):
        """
        Queries for all valid, live ads regardless of geo/lang targeting

        This does not take into account any priority among the ads or any clicks required.
        """
        if not self.should_display_ads():
            return Advertisement.objects.none()

        ad_types = [p["ad_type"] for p in self.placements]

        # Filter ads by campaign, and type first
        advertisements = Advertisement.objects.filter(
            ad_type__slug__in=ad_types,
            flight__campaign__campaign_type__in=self.campaign_types,
            flight__campaign__publishers=self.publisher,
        )

        # Specifying the ad or campaign slug skips filtering by live or date
        if self.ad_slug:
            advertisements = advertisements.filter(slug=self.ad_slug)
        elif self.campaign_slug:
            advertisements = advertisements.filter(
                flight__campaign__slug=self.campaign_slug
            )
        else:
            advertisements = advertisements.filter(
                live=True,
                flight__live=True,
                flight__start_date__lte=get_ad_day().date(),
            )

        # Ensure we fetch flight/campaign/ad_type and filter data so that isn't fetched for each ad
        return advertisements.select_related("flight", "flight__campaign", "ad_type")

    def annotate_queryset(self, candidate_ads):
        """
        Annotates a queryset with additional data

        This is done in an efficient manner to avoid multiple duplicate queries

        * At the flight level: `clicks_today` and `views_today`
        * At the campaign level: `total_value`
        """
        # Get the unique set of flights and campaigns for the candidates
        flights = set()
        campaigns = set()
        for ad in candidate_ads:
            if ad.flight:
                flights.add(ad.flight.pk)
                if ad.flight.campaign:
                    campaigns.add(ad.flight.campaign.pk)

        # Annotate with flight total clicks and views
        for f in Flight.objects.filter(pk__in=flights).annotate(
            num_clicks=models.Sum(models.F("advertisements__impressions__clicks")),
            num_views=models.Sum(models.F("advertisements__impressions__views")),
        ):
            flight_total_clicks = f.num_clicks or 0
            flight_total_views = f.num_views or 0
            for ad in candidate_ads:
                if ad.flight and ad.flight.pk == f.pk:
                    ad.flight.flight_total_clicks = flight_total_clicks
                    ad.flight.flight_total_views = flight_total_views
                    ad.flight.flight_clicks_today = 0
                    ad.flight.flight_views_today = 0

        # Annotate with flight clicks/views today
        # Note: this could be combined with the above and simplified starting in Django 2.0
        #  which supports `filter` on aggregates
        # https://docs.djangoproject.com/en/2.0/topics/db/aggregation/#filtering-on-annotations
        for ad in candidate_ads:
            if ad.flight:
                ad.flight.flight_clicks_today = 0
                ad.flight.flight_views_today = 0
        for impression in AdImpression.objects.filter(
            date=get_ad_day().date(), advertisement__flight__pk__in=flights
        ).select_related("advertisement", "advertisement__flight"):
            for ad in candidate_ads:
                if ad.flight and ad.flight.pk == impression.advertisement.flight.pk:
                    ad.flight.flight_clicks_today += impression.clicks
                    ad.flight.flight_views_today += impression.views

        # Annotate with campaign total value
        for c in Campaign.objects.filter(pk__in=campaigns).annotate(
            value=models.Sum(
                (
                    models.F("flights__advertisements__impressions__clicks")
                    * models.F("flights__cpc")
                )
                + (
                    models.F("flights__advertisements__impressions__views")
                    * models.F("flights__cpm")
                    / 1000
                ),
                output_field=models.FloatField(),
            )
        ):
            campaign_total_value = c.value or 0
            for ad in candidate_ads:
                if ad.flight and ad.flight.campaign and ad.flight.campaign.pk == c.pk:
                    ad.flight.campaign.campaign_total_value = campaign_total_value

        return candidate_ads

    def filter_ads(self, candidate_ads):
        """
        Apply targeting

        Filters ads based on:

        * placements requested
        * $ left on the campaign
        * flight clicks needed today to keep on pace
        * geo and programming language filters
        """
        filtered_ads = []

        if self.campaign_slug or self.ad_slug:
            # Skip filtering if the ad or campaign are specified
            return candidate_ads

        for advertisement in candidate_ads:
            flight = advertisement.flight
            campaign = flight.campaign

            # Skip if we aren't meant to show to this country/state/dma
            if not flight.show_to_geo(
                self.country_code, self.region_code, self.metro_code
            ):
                continue

            # Skip if we aren't meant to show to these keywords
            if not flight.show_to_keywords(self.keywords):
                continue

            # If there's no valid place where this ad can go, skip it
            if not self.get_placement(advertisement):
                continue

            # Skip if there are no clicks or views needed today (ad pacing)
            if flight.weighted_clicks_needed_today() <= 0:
                continue

            # Don't show the ad if it campaign meets or exceeds its max sale value
            if (
                campaign
                and campaign.max_sale_value
                and campaign.total_value() >= campaign.max_sale_value
            ):
                continue

            filtered_ads.append(advertisement)

        return filtered_ads


class AdvertisingDisabledBackend(BaseAdDecisionBackend):

    """A backend where no ads are displayed"""

    def get_ad_and_placement(self):
        return None, None

    def should_display_ads(self):
        return False


class AdvertisingEnabledBackend(BaseAdDecisionBackend):

    """A backend where ads are displayed (default ad order)"""

    def choose_ad(self, ads):
        """
        Choose a ad among the candidates

        This implementation picks the first ad but should be overridden in
        more sophisticated subclasses.
        """
        if ads:
            return ads[0]

        return None

    def get_ad_and_placement(self):
        """
        Get an ad and the matching placement

        Subclasses probably will not override this method and instead override
        `choose_ad` which actually chooses among the candidates ads.
        """
        ads = self.get_ads_queryset()
        ads = self.annotate_queryset(ads)
        ads = self.filter_ads(ads)
        chosen_ad = self.choose_ad(ads)

        if chosen_ad:
            return chosen_ad, self.get_placement(chosen_ad)

        return None, None


class ProbabilisticClicksNeededBackend(AdvertisingEnabledBackend):

    """
    A backend where ads are randomly selected weighted by the flight clicks needed today

    * Randomly select a paid ad based with random weights based on clicks needed
    * If no matching paid ads, randomly select a community ad
    * If no matching community ad, randomly select a house ad
    """

    def choose_ad(self, ads):
        if ads and (self.ad_slug or self.campaign_slug):
            # Ignore priorities for forcing a ad/campaign
            return random.choice(ads)

        chosen_flight = self._choose_flight(ads)
        chosen_ad = self._choose_ad_from_flight(
            [ad for ad in ads if ad.flight == chosen_flight]
        )

        return chosen_ad

    def _choose_flight(self, ads):
        """Choose a flight based on the possible matching ads"""
        paid_ads = [
            ad for ad in ads if ad.flight.campaign.campaign_type == PAID_CAMPAIGN
        ]
        community_ads = [
            ad for ad in ads if ad.flight.campaign.campaign_type == COMMUNITY_CAMPAIGN
        ]
        house_ads = [
            ad for ad in ads if ad.flight.campaign.campaign_type == HOUSE_CAMPAIGN
        ]

        for ad_list in (paid_ads, community_ads, house_ads):
            # Group the ads by flight
            possible_flights = {ad.flight for ad in ad_list}

            # Choose a flight based on the impressions needed
            flight_range = []
            total_clicks_needed = 0
            for flight in possible_flights:
                # If any impressions/clicks are needed, add this flight
                # to the possible list of flights
                if any(
                    (
                        (flight.clicks_needed_today() > 0),
                        (flight.views_needed_today() > 0),
                    )
                ):
                    # NOTE: takes into account views for CPM ads
                    weighted_clicks_needed_today = flight.weighted_clicks_needed_today()

                    flight_range.append(
                        [
                            total_clicks_needed,
                            total_clicks_needed + weighted_clicks_needed_today,
                            flight,
                        ]
                    )
                    total_clicks_needed += weighted_clicks_needed_today

            choice = random.randint(0, total_clicks_needed)
            for min_clicks, max_clicks, flight in flight_range:
                if min_clicks <= choice <= max_clicks:
                    return flight

        return None

    def _choose_ad_from_flight(self, flight_ads):
        """Choose a random ad from the flight based on the placement priority"""
        max_priority = 10
        weighted_ad_choices = []
        for advertisement in flight_ads:
            placement = self.get_placement(advertisement)
            priority = placement.get("priority", 1)
            for _ in range(max_priority + 1 - priority):
                weighted_ad_choices.append(advertisement)

        if weighted_ad_choices:
            return random.choice(weighted_ad_choices)

        return None
