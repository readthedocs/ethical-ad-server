import datetime
import unittest

from django.conf import settings
from django.core.cache import caches
from django.test import TestCase
from django.test import override_settings
from django.test.client import RequestFactory
from django_dynamic_fixture import get
from user_agents import parse

from ..constants import AFFILIATE_CAMPAIGN
from ..constants import CLICKS
from ..constants import COMMUNITY_CAMPAIGN
from ..constants import HOUSE_CAMPAIGN
from ..constants import PAID_CAMPAIGN
from ..constants import VIEWS
from ..decisionengine import get_ad_decision_backend
from ..decisionengine.backends import AdvertisingDisabledBackend
from ..decisionengine.backends import AdvertisingEnabledBackend
from ..decisionengine.backends import ProbabilisticFlightBackend
from ..models import AdType
from ..models import Advertisement
from ..models import Campaign
from ..models import Flight
from ..models import Publisher
from ..models import PublisherGroup
from ..utils import GeolocationData
from ..utils import get_ad_day


if "adserver.analyzer" in settings.INSTALLED_APPS:
    from ..analyzer.models import AnalyzedUrl
else:
    AnalyzedUrl = None


class DecisionEngineTests(TestCase):
    def setUp(self):
        self.publisher = get(
            Publisher, slug="test-publisher", allow_paid_campaigns=True
        )
        self.publisher_group = get(PublisherGroup)
        self.publisher_group.publishers.add(self.publisher)

        self.ad_type = get(AdType, has_image=False, slug="z")
        self.campaign = get(Campaign, publisher_groups=[self.publisher_group])
        self.include_flight = get(
            Flight,
            live=True,
            campaign=self.campaign,
            sold_clicks=1_000,
            cpc=2.0,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            # Only show in US,CA,MX
            targeting_parameters={"include_countries": ["US", "CA", "MX"]},
            pacing_interval=24 * 60 * 60,
        )

        self.cpm_flight = get(
            Flight,
            live=True,
            campaign=self.campaign,
            sold_clicks=0,
            sold_impressions=10_000,
            cpm=3.50,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            targeting_parameters={"include_countries": ["US", "CA", "MX"]},
            pacing_interval=24 * 60 * 60,
        )

        self.advertisement1 = get(
            Advertisement,
            name="ad-slug",
            slug="ad-slug",
            link="http://example.com",
            live=True,
            image=None,
            flight=self.include_flight,
        )
        self.advertisement1.ad_types.add(self.ad_type)

        self.exclude_flight = get(
            Flight,
            live=True,
            campaign=self.campaign,
            sold_clicks=100,
            cpc=5.0,
            # Don't show in AZ
            targeting_parameters={"exclude_countries": ["US", "AZ"]},
            pacing_interval=24 * 60 * 60,
        )

        # Don't show in AZ and only for JS projects
        self.advertisement2 = get(
            Advertisement,
            name="promo2-slug",
            link="http://example.com",
            live=True,
            image=None,
            flight=self.exclude_flight,
        )
        self.advertisement2.ad_types.add(self.ad_type)

        # No filters
        self.basic_flight = get(
            Flight,
            live=True,
            campaign=self.campaign,
            sold_clicks=100,
            cpc=0.0,
            pacing_interval=24 * 60 * 60,
        )
        self.advertisement3 = get(
            Advertisement,
            name="promo3-slug",
            link="http://example.com",
            live=True,
            image=None,
            flight=self.basic_flight,
        )
        self.advertisement3.ad_types.add(self.ad_type)

        self.possible_ads = [
            self.advertisement1,
            self.advertisement2,
            self.advertisement3,
        ]

        self.placements = [{"div_id": "a", "ad_type": "z"}]

        self.factory = RequestFactory()
        self.request = self.factory.get("/")
        self.request.geo = GeolocationData("US", "CA", None)

        self.backend = AdvertisingEnabledBackend(
            request=self.request, placements=self.placements, publisher=self.publisher
        )

        self.probabilistic_backend = ProbabilisticFlightBackend(
            request=self.request, placements=self.placements, publisher=self.publisher
        )

    @override_settings(ADSERVER_DECISION_BACKEND=None)
    def test_ads_disabled(self):
        # Setting no backend defaults to disabled (settings/base has a non-None default)
        backend_class = get_ad_decision_backend()
        backend = backend_class(
            request=self.request, placements=self.placements, publisher=self.publisher
        )
        self.assertTrue(isinstance(backend, AdvertisingDisabledBackend))
        ad, _ = backend.get_ad_and_placement()
        self.assertIsNone(ad)

    def test_before_start_date(self):
        flights = self.backend.get_candidate_flights()
        self.assertTrue(flights.exists())

        # Change flight start dates to the future
        for flight in (self.include_flight, self.exclude_flight, self.basic_flight):
            flight.start_date = get_ad_day().date() + datetime.timedelta(days=1)
            flight.save()

        # Now none of the flights are selected (they start in the future)
        flights = self.backend.get_candidate_flights()
        self.assertFalse(flights.exists())

    def test_nonlive_flight(self):
        flights = self.backend.get_candidate_flights()
        self.assertTrue(flights.exists())

        for flight in (self.include_flight, self.exclude_flight, self.basic_flight):
            flight.live = False
            flight.save()

        flights = self.backend.get_candidate_flights()
        self.assertFalse(flights.exists())

    def test_no_clicks_needed(self):
        self.assertTrue(self.backend.filter_flight(self.include_flight))

        self.include_flight.sold_clicks = 0
        self.include_flight.save()
        self.assertFalse(self.backend.filter_flight(self.include_flight))
        self.assertEqual(self.include_flight.clicks_remaining(), 0)

    def test_no_views_needed(self):
        # Switch promo to a CPM flight
        self.advertisement1.flight = self.cpm_flight
        self.advertisement1.save()

        self.assertTrue(self.backend.filter_flight(self.cpm_flight))

        self.cpm_flight.sold_impressions = 32
        self.cpm_flight.save()
        self.assertTrue(self.backend.filter_flight(self.cpm_flight))
        self.assertEqual(self.cpm_flight.views_remaining(), 32)

        self.cpm_flight.sold_impressions = 0
        self.cpm_flight.save()
        self.assertFalse(self.backend.filter_flight(self.cpm_flight))

    def test_flight_daily_cap(self):
        self.assertTrue(self.backend.filter_flight(self.include_flight))

        # Set a daily cap of $2.50 while each click is $2.00
        # This means we can only show 2 clicks per day before the cap is exceeded
        self.include_flight.daily_cap = 2.5
        self.include_flight.save()
        # Before save, the daily_cap is a float, after saving, it is a decimal
        # This is important because in Python decimals throw when compared to floats
        self.include_flight.refresh_from_db()

        # Simulate 2 clicks
        self.advertisement1.incr(CLICKS, self.publisher)
        self.advertisement1.incr(CLICKS, self.publisher)

        # Clear the `clicks/views_today` cache
        caches[settings.CACHE_LOCAL_ALIAS].clear()

        # Daily cap exceeded
        self.assertFalse(self.backend.filter_flight(self.include_flight))

        self.advertisement2.flight = self.cpm_flight
        self.advertisement2.save()
        self.cpm_flight.cpm = 150.0  # $150 CPM => $0.15 per view
        self.cpm_flight.save()

        # Without the daily cap, this flight is still valid
        self.assertTrue(self.backend.filter_flight(self.cpm_flight))

        self.cpm_flight.daily_cap = 1.0
        self.cpm_flight.save()

        # Simulate 6 views - daily cap not exceeded (6 * 0.15 = 0.90)
        views_to_simulate = 6
        for _ in range(views_to_simulate):
            self.advertisement2.incr(VIEWS, self.publisher)

        caches[settings.CACHE_LOCAL_ALIAS].clear()
        self.assertTrue(self.backend.filter_flight(self.cpm_flight))

        # 7th view exceeds the daily cap
        self.advertisement2.incr(VIEWS, self.publisher)
        caches[settings.CACHE_LOCAL_ALIAS].clear()
        self.assertFalse(self.backend.filter_flight(self.cpm_flight))

    def test_custom_interval(self):
        now = get_ad_day()

        # Switch promo to a CPM flight
        self.advertisement1.flight = self.cpm_flight
        self.advertisement1.save()

        # Set the interval to 1 hour
        self.cpm_flight.pacing_interval = 60 * 60
        self.cpm_flight.save()

        with unittest.mock.patch("adserver.models.timezone") as tz:
            # 1 day (24 intervals) through the flight
            tz.now.return_value = now + datetime.timedelta(days=1)

            # 10_000 views over 31 days, ~13 views needed per hour
            percent_remaining = (30 * 24 - 1) / (31 * 24)
            pace = int(self.cpm_flight.sold_impressions * percent_remaining)

            self.assertEqual(self.cpm_flight.sold_clicks, 0)
            self.assertEqual(self.cpm_flight.sold_impressions, 10_000)
            self.assertEqual(self.cpm_flight.sold_days(), 31 * 24)
            self.assertEqual(self.cpm_flight.clicks_needed_this_interval(), 0)
            self.assertEqual(
                self.cpm_flight.views_needed_this_interval(), 10_000 - pace
            )

            self.assertTrue(self.backend.filter_flight(self.cpm_flight))

            self.cpm_flight.total_views = 10_000 - pace - 1
            self.cpm_flight.save(update_fields=["total_views"])
            self.assertEqual(self.cpm_flight.views_needed_this_interval(), 1)
            self.assertTrue(self.backend.filter_flight(self.cpm_flight))

            # Don't show this flight anymore. It is above pace
            self.cpm_flight.total_views = 10_000 - pace
            self.cpm_flight.save(update_fields=["total_views"])
            self.assertEqual(self.cpm_flight.views_needed_this_interval(), 0)
            self.assertFalse(self.backend.filter_flight(self.cpm_flight))

    def test_flight_clicks(self):
        # Tests the flight_clicks_today, flight_total_clicks optimizations
        backend = AdvertisingEnabledBackend(
            request=self.request,
            placements=self.placements,
            publisher=self.publisher,
            ad_slug=self.advertisement1.slug,
        )

        self.assertEqual(self.include_flight.clicks_remaining(), 1000)
        self.assertEqual(self.include_flight.total_clicks, 0)
        self.assertEqual(self.include_flight.clicks_today(), 0)
        flights = backend.get_candidate_flights()
        self.assertEqual(len(flights), 1)

        # Add 2 clicks
        self.advertisement1.incr(CLICKS, self.publisher)
        self.advertisement1.incr(CLICKS, self.publisher)

        # Refresh the denormalized totals manually since they're no longer updated in real-time
        self.include_flight.refresh_denormalized_totals()
        # Clear the `clicks_today` cache
        caches[settings.CACHE_LOCAL_ALIAS].clear()

        self.assertEqual(self.include_flight.clicks_remaining(), 998)
        self.assertEqual(self.include_flight.total_clicks, 2)
        self.assertEqual(self.include_flight.clicks_today(), 2)

        # Change those 2 clicks to yesterday
        impression = self.advertisement1.impressions.all()[0]
        impression.date = (get_ad_day() - datetime.timedelta(days=1)).date()
        impression.save()

        # Add 1 click for today
        self.advertisement1.incr(CLICKS, self.publisher)
        # Clear the `clicks_today` cache
        caches[settings.CACHE_LOCAL_ALIAS].clear()

        # Refresh the denormalized totals manually since they're no longer updated in real-time
        self.include_flight.refresh_denormalized_totals()

        self.assertEqual(self.include_flight.clicks_remaining(), 997)
        self.assertEqual(self.include_flight.clicks_today(), 1)

    def test_flight_geo_targeting(self):
        # Remove the flight without targeting for this test
        self.basic_flight.live = False
        self.basic_flight.save()

        ad, _ = self.backend.get_ad_and_placement()
        self.assertTrue(ad in (self.advertisement1, self.advertisement2))

        self.backend.geolocation = GeolocationData("US")
        ad, _ = self.backend.get_ad_and_placement()
        self.assertEqual(ad, self.advertisement1)

        self.backend.geolocation = GeolocationData("MX")
        ad, _ = self.backend.get_ad_and_placement()
        self.assertTrue(ad in (self.advertisement1, self.advertisement2))

        self.backend.geolocation = GeolocationData("FO")
        ad, _ = self.backend.get_ad_and_placement()
        self.assertEqual(ad, self.advertisement2)

        self.backend.geolocation = GeolocationData("AZ")
        ad, _ = self.backend.get_ad_and_placement()
        self.assertIsNone(ad)

        self.backend.geolocation = GeolocationData("T1")
        ad, _ = self.backend.get_ad_and_placement()
        self.assertEqual(ad, self.advertisement2)

    def test_flight_mobile_targeting(self):
        # Remove existing flights
        for flight in Flight.objects.all():
            flight.live = False
            flight.save()

        # Setup a new flight and ad
        flight = get(
            Flight,
            campaign=self.campaign,
            live=True,
            sold_clicks=100,
            targeting_parameters={"mobile_traffic": "exclude"},
        )
        self.advertisement1.flight = flight
        self.advertisement1.save()

        ad, _ = self.backend.get_ad_and_placement()
        self.assertEqual(ad, self.advertisement1)

        # Setup a mobile user agent
        self.backend.user_agent = parse(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 10_3_1 like Mac OS X) "
            "AppleWebKit/603.1.30 (KHTML, like Gecko) Version/10.0 Mobile/14E304 Safari/602.1"
        )

        # Ad is excluded since the the flight excludes mobile
        ad, _ = self.backend.get_ad_and_placement()
        self.assertIsNone(ad)

        # Set flight to mobile only
        flight.targeting_parameters = {"mobile_traffic": "only"}
        flight.save()

        ad, _ = self.backend.get_ad_and_placement()
        self.assertEqual(ad, self.advertisement1)

        # Set a non-mobile UA
        self.backend.user_agent = parse(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_5) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.116 Safari/537.36"
        )

        # With a non-mobile UA, the flight should not be chosen
        ad, _ = self.backend.get_ad_and_placement()
        self.assertIsNone(ad)

    def test_exclude_publisher_mobile_traffic(self):
        self.publisher.ignore_mobile_traffic = True
        self.publisher.save()

        # Set a non-mobile UA
        self.backend.user_agent = parse(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_5) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.116 Safari/537.36"
        )

        ad, _ = self.backend.get_ad_and_placement()
        self.assertIsNotNone(ad)

        # Setup a mobile user agent
        self.backend.user_agent = parse(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 10_3_1 like Mac OS X) "
            "AppleWebKit/603.1.30 (KHTML, like Gecko) Version/10.0 Mobile/14E304 Safari/602.1"
        )

        # No ad should be served since the publisher's mobile traffic is excluded from ads
        ad, _ = self.backend.get_ad_and_placement()
        self.assertIsNone(ad)

    def test_flight_days_targeting(self):
        # Remove existing flights
        for flight in Flight.objects.all():
            flight.live = False
            flight.save()

        # Setup a new flight and ad
        flight = get(
            Flight,
            campaign=self.campaign,
            live=True,
            sold_clicks=100,
            targeting_parameters={"days": "monday"},
        )

        self.advertisement1.flight = flight
        self.advertisement1.save()

        # Fun times with dates
        with unittest.mock.patch("adserver.decisionengine.backends.timezone") as tz:
            tz.now.return_value = datetime.datetime(2020, 6, 1, 0, 0, 0)  # Monday

            # Monday targeting works
            ad, _ = self.backend.get_ad_and_placement()
            self.assertEqual(ad, self.advertisement1)

            tz.now.return_value = datetime.datetime(2020, 6, 2, 0, 0, 0)  # Tuesday

            # Ad is excluded
            ad, _ = self.backend.get_ad_and_placement()
            self.assertIsNone(ad)

            # Set to target Tuesday
            flight.targeting_parameters = {"days": ["tuesday"]}
            flight.save()

            # Ad is back
            ad, _ = self.backend.get_ad_and_placement()
            self.assertEqual(ad, self.advertisement1)

    def test_clicks_needed(self):
        self.assertEqual(self.include_flight.clicks_needed_this_interval(), 33)

        clicks_to_simulate = 10
        for _ in range(clicks_to_simulate):
            self.advertisement1.incr(CLICKS, self.publisher)

        # Refresh the denormalized totals manually since they're no longer updated in real-time
        self.include_flight.refresh_denormalized_totals()

        self.assertEqual(self.include_flight.clicks_needed_this_interval(), 23)

        # Set to a date in the past
        self.include_flight.end_date = get_ad_day().date() - datetime.timedelta(days=2)
        self.assertEqual(
            self.include_flight.clicks_needed_this_interval(),
            self.include_flight.sold_clicks - clicks_to_simulate,
        )

    def test_views_needed(self):
        # Switch promo to a CPM flight
        self.advertisement1.flight = self.cpm_flight
        self.advertisement1.save()

        self.assertEqual(self.cpm_flight.clicks_needed_this_interval(), 0)
        # 0% through the flight, 31 days
        self.assertEqual(self.cpm_flight.views_needed_this_interval(), 323)

        views_to_simulate = 10
        for _ in range(views_to_simulate):
            self.advertisement1.incr(VIEWS, self.publisher)

        # Refresh the denormalized totals manually since they're no longer updated in real-time
        self.cpm_flight.refresh_denormalized_totals()

        self.assertEqual(self.cpm_flight.views_needed_this_interval(), 313)

        # Set to a date in the past
        self.cpm_flight.end_date = get_ad_day().date() - datetime.timedelta(days=2)
        self.assertEqual(
            self.cpm_flight.views_needed_this_interval(),
            self.cpm_flight.sold_impressions - views_to_simulate,
        )

    def test_database_queries_made(self):
        # Clear the local cache to ensure a cold start for this test
        caches[settings.CACHE_LOCAL_ALIAS].clear()

        with self.assertNumQueries(1):
            flights = list(self.probabilistic_backend.get_candidate_flights())
            self.assertEqual(len(flights), 3)

        with self.assertNumQueries(5):
            # Five queries total to select a flight on cold cache:
            # 1. Get all the candidate flights
            # 2. Prefetch related ads
            # 3. Prefetch related ad types
            # 4-5. Region/CountryRegion geo data (only on first call; cached afterward)
            flight = self.probabilistic_backend.select_flight()

        with self.assertNumQueries(0):
            # No queries because we used the prefetched ads
            ad = self.probabilistic_backend.select_ad_for_flight(flight)
            self.assertTrue(ad in self.possible_ads, ad)

        with self.assertNumQueries(3):
            # On repeated calls, Region/geo data is in the local cache (no extra queries)
            # Three total queries to get an ad placement:
            # 1. Get all the candidate flights (with prefetch for ads/adtypes)
            # 2. Prefetch related ads
            # 3. Prefetch related ad types
            ad, _ = self.probabilistic_backend.get_ad_and_placement()
            self.assertTrue(ad in self.possible_ads, ad)

    def test_views_today_clicks_today_caching(self):
        """Verify that views_today/clicks_today use a local cache to reduce DB queries."""
        caches[settings.CACHE_LOCAL_ALIAS].clear()

        # First call queries the database and caches the result
        with self.assertNumQueries(1):
            views = self.include_flight.views_today()
        self.assertEqual(views, 0)

        # Second call uses the local cache - no DB queries
        with self.assertNumQueries(0):
            views = self.include_flight.views_today()
        self.assertEqual(views, 0)

        # First call queries the database and caches the result
        with self.assertNumQueries(1):
            clicks = self.include_flight.clicks_today()
        self.assertEqual(clicks, 0)

        # Second call uses the local cache - no DB queries
        with self.assertNumQueries(0):
            clicks = self.include_flight.clicks_today()
        self.assertEqual(clicks, 0)

        # bypass_cache=True forces a fresh DB query
        with self.assertNumQueries(1):
            views = self.include_flight.views_today(bypass_cache=True)
        self.assertEqual(views, 0)

    def test_click_probability(self):
        # Remove existing flights
        for flight in Flight.objects.all():
            flight.live = False
            flight.save()

        priority_range = [1, 2, 10, 50, 100, 10000]
        start_date = get_ad_day().date()
        end_date = start_date + datetime.timedelta(days=30)
        pacing_interval = 60 * 60 * 24

        flight1 = get(
            Flight,
            start_date=start_date,
            end_date=end_date,
            pacing_interval=pacing_interval,
            campaign=self.campaign,
            live=True,
            sold_clicks=100,
        )
        flight2 = get(
            Flight,
            start_date=start_date,
            end_date=end_date,
            pacing_interval=pacing_interval,
            campaign=self.campaign,
            live=True,
            sold_clicks=100,
        )

        self.advertisement1.flight = flight1
        self.advertisement2.flight = flight2
        self.advertisement1.save()
        self.advertisement2.save()

        for flight1_priority in priority_range:
            for flight2_priority in priority_range:
                # Adjust priorities
                flight1.priority_multiplier = flight1_priority
                flight2.priority_multiplier = flight2_priority
                flight1.save()
                flight2.save()

                flight1_prob = flight1.weighted_clicks_needed_this_interval(
                    self.publisher
                )
                flight2_prob = flight2.weighted_clicks_needed_this_interval(
                    self.publisher
                )
                total = flight1_prob + flight2_prob

                with unittest.mock.patch("random.randint") as randint:
                    randint.return_value = -1
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, None)

                    randint.return_value = 0
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, self.advertisement1)

                    randint.return_value = flight1_prob - 1
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, self.advertisement1)

                    randint.return_value = flight1_prob
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, self.advertisement1)

                    randint.return_value = flight1_prob + 1
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, self.advertisement2)

                    randint.return_value = total - 1
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, self.advertisement2)

                    randint.return_value = total
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, self.advertisement2)

                    randint.return_value = total + 1
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, None)

    def test_flight_matching_priority(self):
        # Remove existing flights
        for flight in Flight.objects.all():
            flight.live = False
            flight.save()

        # Priority 1
        ad_type_a = get(AdType, has_image=False, slug="a")
        # Priority 10
        ad_type_b = get(AdType, has_image=False, slug="b")

        placements = [
            {"div_id": "a", "ad_type": "a", "priority": 1},
            {"div_id": "b", "ad_type": "b", "priority": 10},
        ]

        # Flight 1: Matches placement A (priority 1)
        flight1 = get(
            Flight,
            live=True,
            campaign=self.campaign,
            sold_clicks=1000,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            pacing_interval=24 * 60 * 60,
        )
        ad1 = get(
            Advertisement,
            slug="ad1",
            live=True,
            flight=flight1,
        )
        ad1.ad_types.add(ad_type_a)

        # Flight 2: Matches placement B (priority 10)
        flight2 = get(
            Flight,
            live=True,
            campaign=self.campaign,
            sold_clicks=1000,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            pacing_interval=24 * 60 * 60,
        )
        ad2 = get(
            Advertisement,
            slug="ad2",
            live=True,
            flight=flight2,
        )
        ad2.ad_types.add(ad_type_b)

        backend = ProbabilisticFlightBackend(
            request=self.request, placements=placements, publisher=self.publisher
        )

        flight1_count = 0
        flight2_count = 0
        iterations = 1000

        # Ensure base weights are equal
        self.assertEqual(
            flight1.weighted_clicks_needed_this_interval(self.publisher),
            flight2.weighted_clicks_needed_this_interval(self.publisher),
        )

        for _ in range(iterations):
            selected = backend.select_flight()
            if selected == flight1:
                flight1_count += 1
            elif selected == flight2:
                flight2_count += 1

        # Avoid div by 0 and handle potential 0 counts
        ratio = flight2_count / (flight1_count + 1)

        # Used to be ~1, now should be ~10
        self.assertGreater(ratio, 5.0)

    def test_publisher_campaign_type_restrictions(self):
        self.campaign.campaign_type = PAID_CAMPAIGN
        self.campaign.save()

        self.publisher.allow_paid_campaigns = True
        self.publisher.allow_affiliate_campaigns = False
        self.publisher.allow_community_campaigns = False
        self.publisher.allow_house_campaigns = False
        self.publisher.save()

        backend = ProbabilisticFlightBackend(
            request=self.request, placements=self.placements, publisher=self.publisher
        )
        self.assertIsNotNone(backend.select_flight())

        # After setting the only campaign to a affiliate campaign, no flights are eligible on this publisher
        # Because the publisher only wants paid campaigns
        self.campaign.campaign_type = AFFILIATE_CAMPAIGN
        self.campaign.save()
        self.assertIsNone(backend.select_flight())

        self.publisher.allow_affiliate_campaigns = True
        self.publisher.save()
        backend = ProbabilisticFlightBackend(
            request=self.request, placements=self.placements, publisher=self.publisher
        )
        self.assertIsNotNone(backend.select_flight())

        # Same check for community campaigns
        self.campaign.campaign_type = COMMUNITY_CAMPAIGN
        self.campaign.save()
        self.assertIsNone(backend.select_flight())

        self.publisher.allow_community_campaigns = True
        self.publisher.save()
        backend = ProbabilisticFlightBackend(
            request=self.request, placements=self.placements, publisher=self.publisher
        )
        self.assertIsNotNone(backend.select_flight())

        # Same check for house campaigns
        self.campaign.campaign_type = HOUSE_CAMPAIGN
        self.campaign.save()
        self.assertIsNone(backend.select_flight())

        self.publisher.allow_house_campaigns = True
        self.publisher.save()
        backend = ProbabilisticFlightBackend(
            request=self.request, placements=self.placements, publisher=self.publisher
        )
        self.assertIsNotNone(backend.select_flight())

    def test_campaign_type_priority(self):
        # First disable all the flights from the test case constructor
        for flight in Flight.objects.all():
            flight.live = False
            flight.save()

        flights = self.probabilistic_backend.get_candidate_flights()
        self.assertFalse(flights.exists())

        self.publisher.allow_affiliate_campaigns = True
        self.publisher.save()

        # Have to recreate the backend after changing publisher allow types
        self.probabilistic_backend = ProbabilisticFlightBackend(
            request=self.request, placements=self.placements, publisher=self.publisher
        )

        # Paid
        paid_campaign = get(
            Campaign,
            campaign_type=PAID_CAMPAIGN,
            publisher_groups=[self.publisher_group],
        )
        paid_flight = get(
            Flight,
            campaign=paid_campaign,
            live=True,
            cpc=True,
            sold_clicks=100,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
        )
        paid_ad = get(
            Advertisement,
            name="paid",
            slug="test-paid-ad",
            image=None,
            live=True,
            flight=paid_flight,
        )
        paid_ad.ad_types.add(self.ad_type)

        # Affiliate
        affiliate_campaign = get(
            Campaign,
            campaign_type=AFFILIATE_CAMPAIGN,
            publisher_groups=[self.publisher_group],
        )
        affiliate_flight = get(
            Flight,
            campaign=affiliate_campaign,
            live=True,
            cpc=True,
            sold_clicks=100,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
        )
        affiliate_ad = get(
            Advertisement,
            name="affiliate",
            slug="test-affiliate-ad",
            image=None,
            live=True,
            flight=affiliate_flight,
        )
        affiliate_ad.ad_types.add(self.ad_type)

        # Community
        community_campaign = get(
            Campaign,
            campaign_type=COMMUNITY_CAMPAIGN,
            publisher_groups=[self.publisher_group],
        )
        community_flight = get(
            Flight,
            campaign=community_campaign,
            live=True,
            sold_clicks=100,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
        )
        community_ad = get(
            Advertisement,
            name="community",
            slug="test-community-ad",
            image=None,
            live=True,
            flight=community_flight,
        )
        community_ad.ad_types.add(self.ad_type)

        # House
        house_campaign = get(
            Campaign,
            campaign_type=HOUSE_CAMPAIGN,
            publisher_groups=[self.publisher_group],
        )
        house_campaign.campaign_type = HOUSE_CAMPAIGN
        house_campaign.save()
        house_flight = get(
            Flight,
            campaign=house_campaign,
            live=True,
            sold_clicks=100,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
        )
        house_ad = get(
            Advertisement,
            name="house",
            slug="test-house-ad",
            image=None,
            live=True,
            flight=house_flight,
        )
        house_ad.ad_types.add(self.ad_type)

        # Paid before community
        ad, _ = self.probabilistic_backend.get_ad_and_placement()
        self.assertEqual(ad, paid_ad)

        paid_flight.live = False
        paid_flight.save()

        # Affiliate before house or community
        ad, _ = self.probabilistic_backend.get_ad_and_placement()
        self.assertEqual(ad, affiliate_ad)

        affiliate_flight.live = False
        affiliate_flight.save()

        # Community before house
        ad, _ = self.probabilistic_backend.get_ad_and_placement()
        self.assertEqual(ad, community_ad)

    def test_default_keywords(self):
        self.publisher.default_keywords = "foo,bar,baz,machine-learning"
        self.publisher.save()

        self.backend = AdvertisingEnabledBackend(
            request=self.request, placements=self.placements, publisher=self.publisher
        )

        self.assertEqual(
            sorted(self.backend.keywords), ["bar", "baz", "foo", "machine-learning"]
        )

    @unittest.skipIf(AnalyzedUrl is None, "Analyzer not setup")
    def test_analyzer_keywords(self):
        url = "http://example.com"

        backend = AdvertisingEnabledBackend(
            request=self.request,
            placements=self.placements,
            publisher=self.publisher,
            url=url,
        )
        self.assertEqual(backend.keywords, [])

        AnalyzedUrl.objects.create(
            url=url,
            publisher=self.publisher,
            keywords=["foo", "bar"],
        )

        backend = AdvertisingEnabledBackend(
            request=self.request,
            placements=self.placements,
            publisher=self.publisher,
            url=url,
        )
        self.assertEqual(sorted(backend.keywords), ["bar", "foo"])

    def test_publisher_excluded(self):
        flights = self.probabilistic_backend.get_candidate_flights()
        self.assertTrue(flights.exists())

        # Exclude the one and only publisher
        self.campaign.exclude_publishers.add(self.publisher)

        flights = self.probabilistic_backend.get_candidate_flights()
        self.assertFalse(flights.exists())

    def test_ctr_weighting(self):
        # Remove existing flights
        for flight in Flight.objects.all():
            flight.live = False
            flight.save()

        good_ctr = get(
            Flight,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            cpc=2.5,
            campaign=self.campaign,
            live=True,
            sold_clicks=1000,
            total_clicks=5,
            total_views=1500,
            pacing_interval=24 * 60 * 60,
        )
        bad_ctr = get(
            Flight,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            cpc=5,
            campaign=self.campaign,
            live=True,
            sold_clicks=1000,
            total_clicks=0,
            total_views=5000,
            pacing_interval=24 * 60 * 60,
        )

        # Add bonus probability for good performance
        self.assertEqual(good_ctr.clicks_needed_this_interval(), 28)
        weighting_boost = 10 * 2.5 * 0.333  # 10 (constant) * 2.5 (cpc) * 0.333 (ctr)
        self.assertEqual(
            good_ctr.weighted_clicks_needed_this_interval(), int(28 * weighting_boost)
        )

        # Don't allow down-weighting for bad performance,
        # only add bonus for good performance
        self.assertEqual(bad_ctr.clicks_needed_this_interval(), 33)
        self.assertEqual(bad_ctr.weighted_clicks_needed_this_interval(), 33)

    def test_cpm_weighting(self):
        # Remove existing flights
        for flight in Flight.objects.all():
            flight.live = False
            flight.save()

        low_cost = get(
            Flight,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            cpm=1,
            campaign=self.campaign,
            live=True,
            sold_clicks=1000,
            total_clicks=5,
            total_views=1500,
            pacing_interval=24 * 60 * 60,
        )
        high_cost = get(
            Flight,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            cpm=5,
            campaign=self.campaign,
            live=True,
            sold_clicks=1000,
            total_clicks=5,
            total_views=1500,
            pacing_interval=24 * 60 * 60,
        )

        self.publisher.sampled_ctr = 0.2

        self.assertEqual(low_cost.clicks_needed_this_interval(), 28)
        self.assertEqual(low_cost.weighted_clicks_needed_this_interval(), 28)
        # Publisher CTR has no effect
        self.assertEqual(
            low_cost.weighted_clicks_needed_this_interval(self.publisher), 28
        )

        self.assertEqual(high_cost.clicks_needed_this_interval(), 28)
        self.assertEqual(
            high_cost.weighted_clicks_needed_this_interval(), 28 * high_cost.cpm
        )
        # Publisher CTR has no effect
        self.assertEqual(
            high_cost.weighted_clicks_needed_this_interval(self.publisher),
            28 * high_cost.cpm,
        )

    def test_publisher_weighting_bonus(self):
        # Remove existing flights
        for flight in Flight.objects.all():
            flight.live = False
            flight.save()

        flight = get(
            Flight,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            cpc=2.25,
            campaign=self.campaign,
            live=True,
            sold_clicks=1000,
            total_clicks=0,
            total_views=1500,
            pacing_interval=24 * 60 * 60,
        )

        self.assertEqual(flight.clicks_needed_this_interval(), 33)
        self.assertEqual(flight.weighted_clicks_needed_this_interval(), 33)

        # Check publisher weighting
        self.publisher.sampled_ctr = 0.2
        weighting_bonus = 0.2 * 2.25 * 10  # (ctr) * (cpc) * (constant)
        self.assertEqual(
            flight.weighted_clicks_needed_this_interval(self.publisher),
            int(33 * weighting_bonus),
        )

        self.publisher.sampled_ctr = 2  # VERY high CTR
        weighting_bonus = 10  # capped at 10
        self.assertEqual(
            flight.weighted_clicks_needed_this_interval(self.publisher),
            int(33 * weighting_bonus),
        )

    def test_weighting_bounds(self):
        # Remove existing flights
        for flight in Flight.objects.all():
            flight.live = False
            flight.save()

        super_low = get(
            Flight,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            cpm=1,
            campaign=self.campaign,
            live=True,
            sold_clicks=1000,
            total_clicks=0,
            total_views=1500,
            pacing_interval=24 * 60 * 60,
        )
        high = get(
            Flight,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            cpm=2.5,
            campaign=self.campaign,
            live=True,
            sold_clicks=1000,
            total_clicks=5,
            total_views=100,
            pacing_interval=24 * 60 * 60,
        )
        super_high = get(
            Flight,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            cpm=15,
            campaign=self.campaign,
            live=True,
            sold_clicks=1000,
            total_clicks=5,
            total_views=100,
            pacing_interval=24 * 60 * 60,
        )

        # 1x
        self.assertEqual(super_low.clicks_needed_this_interval(), 33)
        self.assertEqual(
            super_low.weighted_clicks_needed_this_interval(), 33 * super_low.cpm
        )

        # 2.5x
        self.assertEqual(high.clicks_needed_this_interval(), 28)
        self.assertEqual(
            high.weighted_clicks_needed_this_interval(), int(28 * high.cpm)
        )

        # 10x
        self.assertEqual(super_high.clicks_needed_this_interval(), 28)
        self.assertEqual(
            super_high.weighted_clicks_needed_this_interval(), 28 * 10
        )  # maxed out

        # Verify the days overdue priority
        days_overdue = 10
        super_low.end_date = get_ad_day().date() - datetime.timedelta(days=days_overdue)
        overdue_factor = int(days_overdue**1.5)
        self.assertEqual(
            super_low.weighted_clicks_needed_this_interval(),
            super_low.sold_clicks * super_low.cpm * overdue_factor,
        )
