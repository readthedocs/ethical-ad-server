"""Ad decision backends."""

import logging
import random

from django.conf import settings
from django.db import models
from django.utils import timezone
from user_agents import parse

from ..constants import AFFILIATE_CAMPAIGN
from ..constants import ALL_CAMPAIGN_TYPES
from ..constants import COMMUNITY_CAMPAIGN
from ..constants import HOUSE_CAMPAIGN
from ..constants import PAID_CAMPAIGN
from ..constants import PUBLISHER_HOUSE_CAMPAIGN
from ..models import Advertisement
from ..models import Flight
from ..models import Region
from ..models import Topic
from ..utils import get_ad_day
from ..utils import get_client_user_agent


if "adserver.analyzer" in settings.INSTALLED_APPS:
    from ..analyzer.models import AnalyzedUrl
else:
    AnalyzedUrl = None

log = logging.getLogger(__name__)


class BaseAdDecisionBackend:
    """A base decision backend -- other decision backends should extend this."""

    def __init__(self, request, placements, publisher, **kwargs):
        """
        Initialize an ad decision based on the request data.

        :param request: the HttpRequest object with geo data attached from GeolocationMiddleware
        :param placements: possible positions for the ad to go
        :param kwargs: Any additional possible arguments for the backend
        """
        self.request = request
        self.user_agent = parse(get_client_user_agent(request))
        self.placements = placements
        self.publisher = publisher

        self.ad_types = [p["ad_type"] for p in self.placements]
        self.url = kwargs.get("url") or ""

        self.geolocation = request.geo

        # Optional parameters
        self.keywords = kwargs.get("keywords", []) or []
        requested_campaign_types = kwargs.get("campaign_types", []) or []
        if not requested_campaign_types:
            requested_campaign_types = ALL_CAMPAIGN_TYPES

        # Add default keywords from publisher
        if self.publisher.keywords:
            log.debug(
                "Adding default keywords: publisher=%s keywords=%s",
                self.publisher.slug,
                self.publisher.keywords,
            )
            merged_keywords = set(self.keywords) | set(self.publisher.keywords)
            self.keywords = list(merged_keywords)

        analyzer_keywords = self.get_analyzer_keywords()
        if analyzer_keywords:
            log.debug(
                "Adding keywords from the analyzer: url=%s keywords=%s",
                self.url,
                analyzer_keywords,
            )
            merged_keywords = set(self.keywords) | set(analyzer_keywords)
            self.keywords = list(merged_keywords)

        # Publishers can request certain campaign types
        # But only if those types are allowed by database settings
        self.campaign_types = []
        if (
            self.publisher.allow_paid_campaigns
            and PAID_CAMPAIGN in requested_campaign_types
        ):
            self.campaign_types.append(PAID_CAMPAIGN)
        if (
            self.publisher.allow_affiliate_campaigns
            and AFFILIATE_CAMPAIGN in requested_campaign_types
        ):
            self.campaign_types.append(AFFILIATE_CAMPAIGN)
        if (
            self.publisher.allow_community_campaigns
            and COMMUNITY_CAMPAIGN in requested_campaign_types
        ):
            self.campaign_types.append(COMMUNITY_CAMPAIGN)
        if PUBLISHER_HOUSE_CAMPAIGN in requested_campaign_types:
            self.campaign_types.append(PUBLISHER_HOUSE_CAMPAIGN)
        if (
            self.publisher.allow_house_campaigns
            and HOUSE_CAMPAIGN in requested_campaign_types
        ):
            self.campaign_types.append(HOUSE_CAMPAIGN)

        # Remove paid ads if this publisher exceeds their daily cap
        if (
            PAID_CAMPAIGN in self.campaign_types
            and self.publisher.daily_cap
            and self.publisher.get_daily_earn() >= self.publisher.daily_cap
        ):
            log.debug("Publisher has hit their daily cap. publisher=%s", self.publisher)
            self.campaign_types.remove(PAID_CAMPAIGN)

        # The placement index (0-based) for this ad request
        # 1+ means multiple ads on the same page
        self.placement_index = kwargs.get("placement_index") or 0

        # When set, only return a specific ad or ads from a campaign
        self.ad_slug = kwargs.get("ad_slug")
        self.campaign_slug = kwargs.get("campaign_slug")

        self.niche_weights = None

    def get_analyzer_keywords(self):
        """Get keywords for this URL from the analyzer."""
        if not self.url:
            return None

        if "adserver.analyzer" not in settings.INSTALLED_APPS:
            log.debug("Not using Analyzer keywords. Analyzer is not in INSTALLED_APPS.")
            return None

        normalized_url = self.url
        analyzed_url = AnalyzedUrl.objects.filter(
            url=normalized_url, publisher=self.publisher
        ).first()
        if analyzed_url:
            return analyzed_url.keywords

        return None

    def get_ad_and_placement(self):
        """
        Choose an ad to display.

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
        """Gets the first matching placement for a given ad."""
        if not advertisement:
            # Always select the placement if there is only 1 for Decisions
            if len(self.placements) == 1:
                return self.placements[0]
            return None

        for placement in self.placements:
            # A placement "matches" if the ad type matches
            # If the ad or campaign is specified, they must also match
            if (
                placement["ad_type"] in [t.slug for t in advertisement.ad_types.all()]
                and (not self.ad_slug or advertisement.slug == self.ad_slug)
                and (
                    not self.campaign_slug
                    or advertisement.flight.campaign.slug == self.campaign_slug
                )
            ):
                return placement

        return None

    def should_display_ads(self):
        """Whether to not display ads based on the user, request, or other settings."""
        # Check if the publisher is allowed to have multiple placements
        if not self.publisher.allow_multiple_placements and self.placement_index > 0:
            log.info(
                "Multiple placement request on publisher rejected. publisher=%s",
                self.publisher,
            )
            return False

        # If this publisher's mobile traffic is ignored, don't serve anything
        if self.publisher.ignore_mobile_traffic and self.user_agent.is_mobile:
            log.info(
                "Publisher mobile traffic is ignored. publisher=%s", self.publisher
            )
            return False

        return True


class AdvertisingDisabledBackend(BaseAdDecisionBackend):
    """A backend where no ads are displayed."""

    def get_ad_and_placement(self):
        return None, None

    def should_display_ads(self):
        return False


class AdvertisingEnabledBackend(BaseAdDecisionBackend):
    """A backend where ads are displayed (default ad order)."""

    def get_candidate_flights(self):
        """
        Queries for all valid, live flights.

        This does not take into account any priority among the ads or any clicks required.
        """
        if not self.should_display_ads():
            return Flight.objects.none()

        # If the flight is restricted by campaign or ad slug
        # Don't restrict it by anything else (campaign type, live, flight date, publisher, etc.)
        if self.ad_slug:
            log.debug("Restricting ad decision by ad. ad_slug=%s", self.ad_slug)
            flights = Flight.objects.filter(advertisements__slug=self.ad_slug)
        elif self.campaign_slug:
            log.debug(
                "Restricting ad decision by campaign. campaign=%s", self.campaign_slug
            )
            flights = Flight.objects.filter(campaign__slug=self.campaign_slug)
        else:
            flights = (
                Flight.objects.filter(
                    advertisements__ad_types__slug__in=self.ad_types,
                    campaign__campaign_type__in=self.campaign_types,
                )
                .filter(
                    campaign__publisher_groups__in=self.publisher.publisher_groups.all()
                )
                .exclude(campaign__exclude_publishers=self.publisher)
            )

            if self.campaign_types != ALL_CAMPAIGN_TYPES:
                log.debug(
                    "Ads restricted to the following campaign types: %s",
                    self.campaign_types,
                )

            flights = flights.filter(live=True, start_date__lte=get_ad_day().date())

            # Ensure there's a live ad of the chosen types for each flight
            flights = flights.filter(
                advertisements__ad_types__slug__in=self.ad_types,
                advertisements__live=True,
            ).distinct()

        # Ensure we prefetch necessary data so it doesn't result in N queries for each flight
        # Annotate with today's views/clicks to avoid per-flight queries in views_today()/clicks_today()
        today = get_ad_day().date()
        return flights.select_related("campaign").annotate(
            flight_views_today=models.Sum(
                "advertisements__impressions__views",
                filter=models.Q(advertisements__impressions__date=today),
            ),
            flight_clicks_today=models.Sum(
                "advertisements__impressions__clicks",
                filter=models.Q(advertisements__impressions__date=today),
            ),
        )

    def filter_flight(self, flight, regions=None, topics=None):
        """
        Apply flight targeting.

        * $/clicks/views left on the campaign
        * flight clicks needed today to keep on pace
        * geo and keyword filters
        """
        if self.campaign_slug or self.ad_slug:
            # Skip filtering if the ad or campaign are specified
            return True

        # Skip if we aren't meant to show to this country/state/dma
        if not flight.show_to_geo(self.geolocation, regions=regions):
            return False

        # Skip if we aren't meant to show to these keywords
        if not flight.show_to_keywords(self.keywords, topics=topics):
            return False

        # Skip if we aren't meant to show to this traffic because it is mobile or non-mobile
        if not flight.show_to_mobile(self.user_agent.is_mobile):
            return False

        # Skip if this flight is ineligible for this publisher
        if not flight.show_on_publisher(self.publisher):
            return False

        # Skip if we shouldn't show this flight on this domain
        if not flight.show_on_domain(self.url):
            return False

        # Skip if there are no clicks or views needed today/this interval (ad pacing)
        if flight.weighted_clicks_needed_this_interval() <= 0:
            return False

        # Skip if the flight is not meant to show on these days
        if not flight.show_to_day(timezone.now().strftime("%A").lower()):
            return False

        # Skip if the flight if the similarity is not high enough
        if not flight.show_to_niche_targeting(self.niche_weights):
            return False

        # Skip if the flight has reached its daily cap
        if flight.daily_cap_exceeded():
            return False

        return True

    def select_flight(self):
        """Naively select a flight from the candidates."""
        flights = self.get_candidate_flights()

        # Filter and randomly sort
        valid_flights = []
        regions = Region.load_from_cache()
        topics = Topic.load_from_cache()

        for flight in flights:
            if self.filter_flight(flight, regions=regions, topics=topics):
                valid_flights.append(flight)

        if valid_flights:
            return random.choice(valid_flights)

        return None

    def select_ad_for_flight(self, flight):
        """Naively choose an ad from the selected flight."""
        if not flight:
            return None

        return (
            flight.advertisements.filter(live=True, ad_types__slug__in=self.ad_types)
            .order_by("?")
            .first()
        )

    def get_ad_and_placement(self):
        flight = self.select_flight()
        ad = self.select_ad_for_flight(flight)
        return ad, self.get_placement(ad)


class ProbabilisticFlightBackend(AdvertisingEnabledBackend):
    """
    A backend where flights are selected randomly weighted by the clicks needed today.

    * Randomly select a paid ad based with random weights based on clicks needed
    * If no matching paid ads, randomly select a community ad
    * If no matching community ad, randomly select a house ad
    """

    def select_flight(self):
        """
        Select a flight from the candidates.

        * Choose paid over community over house campaigns
        * Prioritize the flight that needs the most impressions
        """
        flights = self.get_candidate_flights()
        flights = flights.prefetch_related(
            models.Prefetch(
                "advertisements",
                queryset=Advertisement.objects.filter(
                    live=True, ad_types__slug__in=self.ad_types
                ),
                to_attr="matching_ads",
            ),
            "matching_ads__ad_types",
        )

        paid_flights = []
        affiliate_flights = []
        community_flights = []
        publisher_house_flights = []
        house_flights = []

        for flight in flights:
            # Separate flights by campaign type, so we can prioritize them in this order
            if flight.campaign.campaign_type == PAID_CAMPAIGN:
                paid_flights.append(flight)
            elif flight.campaign.campaign_type == AFFILIATE_CAMPAIGN:
                affiliate_flights.append(flight)
            elif flight.campaign.campaign_type == COMMUNITY_CAMPAIGN:
                community_flights.append(flight)
            elif flight.campaign.campaign_type == PUBLISHER_HOUSE_CAMPAIGN:
                publisher_house_flights.append(flight)
            else:
                house_flights.append(flight)

        if flights and (self.ad_slug or self.campaign_slug):
            # Ignore priorities for forcing a specific ad/campaign
            return random.choice(flights)

        regions = Region.load_from_cache()
        topics = Topic.load_from_cache()

        # We iterate over the possible flights in order of priority,
        # and serve the first type that has any budget.
        for possible_flights in (
            paid_flights,
            affiliate_flights,
            community_flights,
            publisher_house_flights,
            house_flights,
        ):
            # Choose a flight based on the impressions needed
            flight_range = []
            total_clicks_needed = 0
            self.niche_weights = None

            flights_with_niche_targeting = [
                flight for flight in possible_flights if flight.niche_targeting
            ]

            # Apply niche targeting only when any flight has it.
            # This is to track whether we should do expensive distance queries.
            if (
                flights_with_niche_targeting
                and "ethicalads_ext.embedding" in settings.INSTALLED_APPS
            ):
                # We have to do this here,
                # so we can filter by the weight in the filter_flight call below
                from ethicalads_ext.embedding.utils import get_niche_weights  # noqa

                self.niche_weights = get_niche_weights(
                    url=self.url, flights=flights_with_niche_targeting
                )
                if self.niche_weights:
                    log.debug("Niche targeting weights: %s", self.niche_weights)

            for flight in possible_flights:
                # Handle excluding flights based on targeting
                if not self.filter_flight(flight, regions=regions, topics=topics):
                    continue

                # If any impressions/clicks are needed, add this flight
                # to the possible list of flights
                if any(
                    (
                        (flight.clicks_needed_this_interval() > 0),
                        (flight.views_needed_this_interval() > 0),
                    )
                ):
                    # NOTE: takes into account views for CPM ads
                    # Takes eCPM (CTR * CPC for CPC ads) into account
                    weighted_clicks_needed_this_interval = (
                        flight.weighted_clicks_needed_this_interval(
                            self.publisher,
                        )
                    )

                    # Boost the weight of this flight if it matches a high priority placement
                    priority = 1
                    for ad in flight.matching_ads:
                        placement = self.get_placement(ad)
                        if placement:
                            priority = max(priority, placement.get("priority", 1))

                    weighted_clicks_needed_this_interval *= priority

                    flight_range.append(
                        [
                            total_clicks_needed,
                            total_clicks_needed + weighted_clicks_needed_this_interval,
                            flight,
                        ]
                    )
                    total_clicks_needed += weighted_clicks_needed_this_interval

            # Choose a random flight based on the weights computed above.
            # The higher priority flights will have more total "chances".
            choice = random.randint(0, total_clicks_needed)
            for min_clicks, max_clicks, flight in flight_range:
                if min_clicks <= choice <= max_clicks:
                    return flight

        return None

    def get_ad_ctr_weight(self, ad):
        """
        Apply the ad weighting factor based on the sampled CTR.

        Give better performing ads slightly more weighting.
        The scale ramps up based on how far different the CTRs are.
        For example, in a flight with 2 ads, ad X with 0.1% CTR and ad Y with 0.2% CTR,
        the chances for X are (1+2)/8 ~= 37.5% and the chances for Y are (1+4)/8 ~= 62.5%.

        We can play a bit with these weights if we want.
        """
        weights = {
            0.075: 1,
            0.100: 2,
            0.125: 3,
            0.150: 4,
        }
        ad_weighting = 0
        for threshold, weight in weights.items():
            if ad.sampled_ctr >= threshold and weight > ad_weighting:
                ad_weighting = weight

        return ad_weighting

    def select_ad_for_flight(self, flight):
        """
        Choose an ad from the selected flight filtered requested ``self.ad_types``.

        Apply weighting to the ad based:

        - Requested placement priority
        - Sampled ad CTR
        """
        if not flight:
            return None

        chosen_ad = None
        weighted_ad_choices = []

        if self.ad_slug:
            # Ignore live and adtype checks when forcing a specific ad
            candidate_ads = flight.advertisements.filter(slug=self.ad_slug)
            candidate_ads = candidate_ads.select_related("flight").prefetch_related(
                "ad_types"
            )
        elif hasattr(flight, "matching_ads"):
            candidate_ads = flight.matching_ads
        else:
            candidate_ads = flight.advertisements.filter(
                live=True, ad_types__slug__in=self.ad_types
            )
            candidate_ads = candidate_ads.select_related("flight").prefetch_related(
                "ad_types"
            )

        for advertisement in candidate_ads:
            placement = self.get_placement(advertisement)
            if not placement:
                log.warning(
                    "Couldn't find a matching ad placement. ad=%s, placements=%s",
                    advertisement,
                    self.placements,
                )
                continue

            # The ad placement priority usually based on the ad type
            # The serializer has verified that the maximum value is 10
            priority = placement.get("priority", 1)

            if flight.prioritize_ads_ctr:
                # Give more weighting to high performing ads
                priority += self.get_ad_ctr_weight(advertisement)

            for _ in range(priority):
                weighted_ad_choices.append(advertisement)

        if weighted_ad_choices:
            chosen_ad = random.choice(weighted_ad_choices)
        else:
            log.warning(
                "Chosen flight has no matching live ads! flight=%s, ad_types=%s",
                flight,
                self.ad_types,
            )

        return chosen_ad
