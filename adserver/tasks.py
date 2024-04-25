"""Celery tasks for the ad server."""
import datetime
import logging
from collections import defaultdict

from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site
from django.core import mail
from django.db.models import Count
from django.db.models import F
from django.db.models import FloatField
from django.db.models import Q
from django.db.models import Sum
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _
from django_slack import slack_message
from simple_history.utils import update_change_reason

from .constants import FLIGHT_STATE_CURRENT
from .constants import FLIGHT_STATE_UPCOMING
from .constants import PAID_CAMPAIGN
from .importers import psf
from .models import AdImpression
from .models import Advertisement
from .models import Advertiser
from .models import AdvertiserImpression
from .models import Flight
from .models import GeoImpression
from .models import KeywordImpression
from .models import Offer
from .models import PlacementImpression
from .models import Publisher
from .models import PublisherImpression
from .models import PublisherPaidImpression
from .models import Region
from .models import RegionImpression
from .models import RegionTopicImpression
from .models import Topic
from .models import UpliftImpression
from .reports import PublisherReport
from .utils import calculate_ctr
from .utils import calculate_percent_diff
from .utils import generate_absolute_url
from .utils import get_ad_day
from .utils import get_day
from config.celery_app import app

log = logging.getLogger(__name__)  # noqa


@app.task()
def daily_update_geos(day=None, geo=True, region=True):
    """
    Update the Geo & region index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = get_day(day)

    if not geo and not region:
        log.error("geo or region required, please pass one as True")
        return

    # TODO: Delete the GeoImpression, once we're happy with RegionImpression's
    if geo:
        log.info("Updating GeoImpressions for %s-%s", start_date, end_date)

    if region:
        log.info("Updating RegionImpressions for %s-%s", start_date, end_date)
        # Delete all previous Region impressions
        RegionImpression.objects.using("default").filter(
            date__gte=start_date,
            date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
        ).delete()

    topic_mapping = defaultdict(
        lambda: {
            "decisions": 0,
            "offers": 0,
            "views": 0,
            "clicks": 0,
        }
    )
    queryset = Offer.objects.using(settings.REPLICA_SLUG).filter(
        # For region and topic reports, we are excluding ads that were ineligible to be paid
        # from the aggregations unless the publisher isn't approved for paid ads.
        # This will give us more accurate KPIs on fill rates for paid publishers.
        Q(paid_eligible=True) | Q(publisher__allow_paid_campaigns=False),
        date__gte=start_date,
        date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
    )
    for values in (
        queryset.values("advertisement", "country", "publisher")
        .annotate(
            total_decisions=Count("country"),
            total_offers=Count("country", filter=Q(advertisement__isnull=False)),
            total_views=Count("country", filter=Q(viewed=True)),
            total_clicks=Count("country", filter=Q(clicked=True)),
        )
        .filter(total_decisions__gt=0)
        .order_by("-total_decisions")
        .iterator()
    ):
        country = values["country"]
        if geo:
            impression, _ = GeoImpression.objects.using("default").get_or_create(
                publisher_id=values["publisher"],
                advertisement_id=values["advertisement"],
                country=country,
                date=start_date,
            )
            GeoImpression.objects.using("default").filter(pk=impression.pk).update(
                decisions=values["total_decisions"],
                offers=values["total_offers"],
                views=values["total_views"],
                clicks=values["total_clicks"],
            )

        if region:
            _region = Region.get_region_from_country_code(country)

            publisher = values["publisher"]
            advertisement = values["advertisement"]
            topic_mapping[f"{advertisement}:{publisher}:{_region}"][
                "decisions"
            ] += values["total_decisions"]
            topic_mapping[f"{advertisement}:{publisher}:{_region}"]["offers"] += values[
                "total_offers"
            ]
            topic_mapping[f"{advertisement}:{publisher}:{_region}"]["views"] += values[
                "total_views"
            ]
            topic_mapping[f"{advertisement}:{publisher}:{_region}"]["clicks"] += values[
                "total_clicks"
            ]

    if region:
        for data, value in topic_mapping.items():
            ad, publisher, _region = data.split(":")
            # Handle the conversion of None
            if ad == "None":
                ad = None
            impression, _ = RegionImpression.objects.using("default").get_or_create(
                publisher_id=publisher,
                advertisement_id=ad,
                region=_region,
                date=start_date,
            )
            RegionImpression.objects.using("default").filter(pk=impression.pk).update(
                decisions=F("decisions") + value["decisions"],
                offers=F("offers") + value["offers"],
                views=F("views") + value["views"],
                clicks=F("clicks") + value["clicks"],
            )


@app.task()
def daily_update_placements(day=None):
    """
    Update the Placement index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = get_day(day)

    log.info("Updating PlacementImpressions for %s-%s", start_date, end_date)

    queryset = Offer.objects.using(settings.REPLICA_SLUG).filter(
        date__gte=start_date,
        date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
    )

    for values in (
        queryset.values("publisher", "advertisement", "div_id", "ad_type_slug")
        .annotate(
            total_decisions=Count("div_id"),
            total_offers=Count("div_id", filter=Q(advertisement__isnull=False)),
            total_views=Count("div_id", filter=Q(viewed=True)),
            total_clicks=Count("div_id", filter=Q(clicked=True)),
        )
        .filter(total_decisions__gt=0)
        .filter(publisher__record_placements=True)
        .exclude(div_id__regex=r"(rtd-\w{4}|ad_\w{4}).*")
        .order_by("-total_decisions")
        .iterator()
    ):

        impression, _ = PlacementImpression.objects.using("default").get_or_create(
            publisher_id=values["publisher"],
            advertisement_id=values["advertisement"],
            div_id=values["div_id"],
            ad_type_slug=values["ad_type_slug"],
            date=start_date,
        )
        PlacementImpression.objects.using("default").filter(pk=impression.pk).update(
            decisions=values["total_decisions"],
            offers=values["total_offers"],
            views=values["total_views"],
            clicks=values["total_clicks"],
        )


@app.task()
def daily_update_impressions(day=None):
    """
    Update the AdImpression index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = get_day(day)

    log.info("Updating AdImpressions for %s-%s", start_date, end_date)

    queryset = Offer.objects.using(settings.REPLICA_SLUG).filter(
        date__gte=start_date,
        date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
    )

    for values in (
        queryset.values("publisher", "advertisement")
        # This needs to be publisher and not advertisement to gets decisions properly
        .annotate(
            total_decisions=Count("publisher"),
            total_offers=Count("publisher", filter=Q(advertisement__isnull=False)),
            total_views=Count("publisher", filter=Q(viewed=True)),
            total_clicks=Count("publisher", filter=Q(clicked=True)),
            view_time=Sum("view_time"),
        )
        .filter(total_decisions__gt=0)
        .order_by("-total_decisions")
        .iterator()
    ):

        impression, _ = AdImpression.objects.using("default").get_or_create(
            publisher_id=values["publisher"],
            advertisement_id=values["advertisement"],
            date=start_date,
        )
        AdImpression.objects.using("default").filter(pk=impression.pk).update(
            decisions=values["total_decisions"],
            offers=values["total_offers"],
            views=values["total_views"],
            clicks=values["total_clicks"],
            view_time=values["view_time"],
        )


@app.task()
def daily_update_keywords(day=None):
    """
    Update the KeywordImpression index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = get_day(day)

    log.info("Updating KeywordImpression for %s-%s", start_date, end_date)

    # Remove all old keyword impressions, because they are cumulative
    KeywordImpression.objects.using("default").filter(
        date__gte=start_date,
        date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
    ).delete()

    keyword_mapping = defaultdict(
        lambda: {
            "decisions": 0,
            "offers": 0,
            "views": 0,
            "clicks": 0,
        }
    )

    queryset = Offer.objects.using(settings.REPLICA_SLUG).filter(
        date__gte=start_date,
        date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
    )

    all_topics = Topic.load_from_cache()

    for values in (
        queryset.values("publisher", "advertisement", "keywords", "viewed", "clicked")
        .annotate(
            total_decisions=Count("keywords"),
            total_offers=Count("keywords", filter=Q(advertisement__isnull=False)),
            total_views=Count("keywords", filter=Q(viewed=True)),
            total_clicks=Count("keywords", filter=Q(clicked=True)),
        )
        .order_by("-total_decisions")
        .values(
            "publisher",
            "advertisement",
            "keywords",
            "advertisement__flight__targeting_parameters",
            "total_decisions",
            "total_offers",
            "total_views",
            "total_clicks",
        )
        .iterator()
    ):
        if not (
            values["keywords"] and values["advertisement__flight__targeting_parameters"]
        ):
            continue

        page_keywords = set(values["keywords"])
        flight_targeting = values["advertisement__flight__targeting_parameters"]

        flight_keywords = set(flight_targeting.get("include_keywords", {}))
        flight_topics = set(flight_targeting.get("include_topics", {}))

        # If this flight targeted topics, add those as well
        for topic in flight_topics:
            if topic in all_topics:
                for kw in all_topics[topic]:
                    flight_keywords.add(kw)

        # Only store keywords where the advertiser targeting
        # matched the keywords on the offer
        matched_keywords = page_keywords & flight_keywords

        for keyword in matched_keywords:
            advertisement_id = values["advertisement"]
            publisher_id = values["publisher"]
            index = f"{advertisement_id}:{publisher_id}:{keyword}"

            keyword_mapping[index]["decisions"] += values["total_decisions"]
            keyword_mapping[index]["offers"] += values["total_offers"]
            keyword_mapping[index]["views"] += values["total_views"]
            keyword_mapping[index]["clicks"] += values["total_clicks"]

    for data, value in keyword_mapping.items():
        ad, publisher, keyword = data.split(":")
        if ad == "None":
            ad = None

        impression, _ = KeywordImpression.objects.using("default").get_or_create(
            date=start_date,
            publisher_id=publisher,
            advertisement_id=ad,
            keyword=keyword,
        )
        KeywordImpression.objects.using("default").filter(pk=impression.pk).update(
            decisions=F("decisions") + value["decisions"],
            offers=F("offers") + value["offers"],
            views=F("views") + value["views"],
            clicks=F("clicks") + value["clicks"],
        )


@app.task()
def daily_update_regiontopic(day=None):
    """
    Update the RegionTopicImpression index each day.

    Each data point will have one region, but multiple possible topics.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = get_day(day)

    log.info("Updating RegionTopic's for %s-%s", start_date, end_date)

    # Remove all old impressions, because they are cumulative
    RegionTopicImpression.objects.using("default").filter(
        date__gte=start_date, date__lt=end_date
    ).delete()

    all_topics = Topic.load_from_cache()

    topic_mapping = defaultdict(
        lambda: {
            "decisions": 0,
            "offers": 0,
            "views": 0,
            "clicks": 0,
        }
    )
    queryset = Offer.objects.using(settings.REPLICA_SLUG).filter(
        # For region and topic reports, we are excluding ads that were ineligible to be paid
        # from the aggregations unless the publisher isn't approved for paid ads.
        # This will give us more accurate KPIs on fill rates for paid publishers.
        Q(paid_eligible=True) | Q(publisher__allow_paid_campaigns=False),
        date__gte=start_date,
        date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
    )
    for values in (
        queryset.values("advertisement", "keywords", "country")
        .annotate(
            total_decisions=Count("country"),
            total_offers=Count("country", filter=Q(advertisement__isnull=False)),
            total_views=Count("country", filter=Q(viewed=True)),
            total_clicks=Count("country", filter=Q(clicked=True)),
        )
        .filter(total_decisions__gt=0)
        .order_by("-total_decisions")
        .values(
            "keywords",
            "advertisement",
            "country",
            "total_decisions",
            "total_offers",
            "total_views",
            "total_clicks",
        )
        .iterator()
    ):
        if not (values["keywords"] and values["country"]):
            continue

        keywords = values["keywords"]
        country = values["country"]
        ad = values["advertisement"]
        publisher_keywords = set(keywords)

        topics = set()
        for keyword in publisher_keywords:
            for topic in all_topics:
                if keyword in all_topics[topic]:
                    topics.add(topic)

        # If nothing gets set as a topic, assign it other
        if not topics:
            topics.add("other")

        region = Region.get_region_from_country_code(country)

        # Aggregate data into topic_mapping to save doing queries until we have everything counted
        # This is important because we can't query on keywords, so we have a lot of records that increment
        # the total count on the region & topic.
        for topic in topics:
            topic_mapping[f"{ad}:{region}:{topic}"]["decisions"] += values[
                "total_decisions"
            ]
            topic_mapping[f"{ad}:{region}:{topic}"]["offers"] += values["total_offers"]
            topic_mapping[f"{ad}:{region}:{topic}"]["views"] += values["total_views"]
            topic_mapping[f"{ad}:{region}:{topic}"]["clicks"] += values["total_clicks"]

    for data, value in topic_mapping.items():
        ad, region, topic = data.split(":")
        # Handle the conversion of
        if ad == "None":
            ad = None
        impression, _ = RegionTopicImpression.objects.using("default").get_or_create(
            date=start_date, advertisement_id=ad, region=region, topic=topic
        )
        # these are a sum because we can't query for specific keywords from postgres,
        # so a specific publisher and advertisement set could return the same keyword:
        # ['python', 'django'] and ['python, 'flask'] both are `python` in this case.
        RegionTopicImpression.objects.using("default").filter(pk=impression.pk).update(
            decisions=F("decisions") + value["decisions"],
            offers=F("offers") + value["offers"],
            views=F("views") + value["views"],
            clicks=F("clicks") + value["clicks"],
        )


@app.task()
def daily_update_uplift(day=None):
    """
    Generate the daily index of UpliftImpressions.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = get_day(day)

    log.info("Updating uplift for %s-%s", start_date, end_date)

    queryset = Offer.objects.using(settings.REPLICA_SLUG).filter(
        date__gte=start_date,
        date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
    )

    for values in (
        queryset.values("publisher", "advertisement")
        .annotate(
            total_decisions=Count("uplifted"),
            total_offers=Count("uplifted", filter=Q(advertisement__isnull=False)),
            total_views=Count("uplifted", filter=Q(viewed=True)),
            total_clicks=Count("uplifted", filter=Q(clicked=True)),
        )
        .filter(total_decisions__gt=0)
        .order_by("-total_decisions")
        .values(
            "publisher",
            "advertisement",
            "total_decisions",
            "total_offers",
            "total_views",
            "total_clicks",
        )
        .iterator()
    ):
        impression, _ = UpliftImpression.objects.using("default").get_or_create(
            publisher_id=values["publisher"],
            advertisement_id=values["advertisement"],
            date=start_date,
        )
        UpliftImpression.objects.using("default").filter(pk=impression.pk).update(
            decisions=values["total_decisions"],
            offers=values["total_offers"],
            views=values["total_views"],
            clicks=values["total_clicks"],
        )


@app.task()
def daily_update_advertisers(day=None):
    """
    Generate the daily index of AdvertiserImpressions.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = get_day(day)

    log.info("Updating advertiser impressions for %s-%s", start_date, end_date)

    # Important: uses the *already calculated* AdImpression index
    # This should make this much faster than using the Offers table
    queryset = AdImpression.objects.using(settings.REPLICA_SLUG).filter(
        date__gte=start_date,
        date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
    )

    for values in (
        queryset.values(
            "advertisement__flight__campaign__advertiser__name",
            "advertisement__flight__campaign__advertiser_id",
        )
        .annotate(
            total_decisions=Sum("decisions"),
            total_offers=Sum("offers"),
            total_views=Sum("views"),
            total_clicks=Sum("clicks"),
            total_spend=Sum(
                (F("clicks") * F("advertisement__flight__cpc"))
                + (F("views") * F("advertisement__flight__cpm") / 1000),
                output_field=FloatField(),
            ),
        )
        .filter(advertisement__isnull=False)
        .order_by("advertisement__flight__campaign__advertiser__name")
        .iterator()
    ):
        advertiser_id = values["advertisement__flight__campaign__advertiser_id"]
        impression, _ = AdvertiserImpression.objects.using("default").get_or_create(
            advertiser_id=advertiser_id,
            date=start_date,
        )
        AdvertiserImpression.objects.using("default").filter(pk=impression.pk).update(
            decisions=values["total_decisions"],
            offers=values["total_offers"],
            views=values["total_views"],
            clicks=values["total_clicks"],
            spend=values["total_spend"],
        )


@app.task()
def daily_update_publishers(day=None):
    """
    Generate the daily index of PublisherImpressions.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = get_day(day)

    log.info("Updating publisher impressions for %s-%s", start_date, end_date)

    # Important: uses the *already calculated* AdImpression index
    # This should make this much faster than using the Offers table
    queryset = AdImpression.objects.using(settings.REPLICA_SLUG).filter(
        date__gte=start_date,
        date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
    )

    for model, filters in (
        (PublisherImpression, {}),
        (
            PublisherPaidImpression,
            {"advertisement__flight__campaign__campaign_type": PAID_CAMPAIGN},
        ),
    ):
        for values in (
            queryset.filter(**filters)
            .values("publisher__name", "publisher_id")
            .annotate(
                total_decisions=Sum("decisions"),
                total_offers=Sum(
                    "offers", filter=Q(advertisement__isnull=False), default=0
                ),
                total_views=Sum("views"),
                total_clicks=Sum("clicks"),
                total_revenue=Sum(
                    (F("clicks") * F("advertisement__flight__cpc"))
                    + (F("views") * F("advertisement__flight__cpm") / 1000),
                    output_field=FloatField(),
                    default=0,
                ),
            )
            .order_by("publisher__name")
            .iterator()
        ):
            impression, _ = model.objects.using("default").get_or_create(
                publisher_id=values["publisher_id"],
                date=start_date,
            )
            model.objects.using("default").filter(pk=impression.pk).update(
                decisions=values["total_decisions"],
                offers=values["total_offers"],
                views=values["total_views"],
                clicks=values["total_clicks"],
                revenue=values["total_revenue"],
            )


@app.task(time_limit=60 * 60 * 4)
def daily_update_reports():
    """Update today's report data rather than the previous day."""
    day, _ = get_day()
    update_previous_day_reports(day)


@app.task(time_limit=60 * 60 * 4)
def update_previous_day_reports(day=None):
    """
    Complete all report data for the previous day.

    :arg day: An optional datetime object representing a day.
    """
    start_date, _ = get_day(day)

    if not day:
        # If not specified,
        # do the previous day now that the day is complete
        start_date -= datetime.timedelta(days=1)

    # Do all reports
    daily_update_geos(start_date)
    daily_update_placements(start_date)
    daily_update_impressions(start_date)
    daily_update_advertisers(start_date)  # Important: after daily_update_impressions
    daily_update_publishers(start_date)  # Important: after daily_update_impressions
    daily_update_keywords(start_date)
    daily_update_uplift(start_date)
    daily_update_regiontopic(start_date)

    # Updates an aggregation on each paid flight
    update_flight_traffic_fill.apply_async()

    if not day:
        # Send notification to Slack about previous day's reports
        # Don't send this notification if run manually
        slack_message(
            "adserver/slack/generic-message.slack",
            {
                "text": f"Completed aggregating report data for yesterday ({start_date:%Y-%m-%d}). :page_with_curl:"
            },
        )


@app.task()
def remove_old_report_data(days=366):
    """
    Remove old report data for selected reports from the database.

    Removes:
    - geo breakdown data
    - placement data
    - keyword data
    - uplift data
    - regiontopic data
    """
    old_cutoff = get_ad_day() - datetime.timedelta(days=days)

    models = (
        GeoImpression,
        PlacementImpression,
        KeywordImpression,
        UpliftImpression,
        RegionTopicImpression,
    )

    for model in models:
        model_name = model.__name__
        log.info("Deleting old %s before %s", model_name, old_cutoff)
        model.objects.filter(date__lt=old_cutoff).delete()


@app.task()
def remove_old_client_ids(days=90):
    """Remove old Client IDs which are used for short periods for fraud prevention."""
    old_cutoff = get_ad_day() - datetime.timedelta(days=days)
    while True:
        offer_ids = Offer.objects.filter(
            date__lt=old_cutoff, client_id__isnull=False
        ).values("pk")[:1000]
        offers_changed = Offer.objects.filter(pk__in=offer_ids).update(client_id=None)
        if not offers_changed:
            break


@app.task()
def calculate_publisher_ctrs(days=7):
    """Calculate average CTRs for paid ads on a publisher for the last X days."""
    sample_cutoff = get_ad_day() - datetime.timedelta(days=days)

    for publisher in Publisher.objects.filter(allow_paid_campaigns=True):
        queryset = AdImpression.objects.filter(
            date__gte=sample_cutoff,
            publisher=publisher,
            advertisement__flight__campaign__campaign_type=PAID_CAMPAIGN,
        )
        report = PublisherReport(queryset)
        report.generate()

        if report.total["views"] > 0:
            publisher.sampled_ctr = report.total["ctr"]
            publisher.save()


@app.task()
def calculate_ad_ctrs(days=7, min_views=1_000):
    """Calculate sampled CTRs for all active ads for the last X days."""
    sample_cutoff = get_ad_day() - datetime.timedelta(days=days)

    for ad in Advertisement.objects.filter(live=True, flight__live=True):
        result = AdImpression.objects.filter(
            date__gte=sample_cutoff,
            advertisement=ad,
        ).aggregate(
            total_views=Sum("views"),
            total_clicks=Sum("clicks"),
        )
        # These can be `None` if there are NO results in the timeframe
        total_views = result["total_views"] or 0
        total_clicks = result["total_clicks"] or 0

        if total_views >= min_views:
            ad.sampled_ctr = calculate_ctr(total_clicks, total_views)
            ad.save()


@app.task()
def notify_on_ad_image_change(advertisement_id):
    ad = Advertisement.objects.filter(id=advertisement_id).first()
    if not ad or not ad.image:
        log.warning("Invalid ad passed to 'notify_on_ad_image_change'")
        return

    ad_url = generate_absolute_url(ad.get_absolute_url())
    message = f"{ad.name} ({ad_url}) image uploaded: {ad.image.url}"

    log.info(message)
    slack_message(
        "adserver/slack/generic-message.slack",
        {"text": message},
    )


@app.task()
def notify_of_completed_flights():
    """Send a note and close flights which completed in the last day."""
    cutoff = get_ad_day() - datetime.timedelta(days=1)

    completed_flights_by_advertiser = defaultdict(list)
    for flight in Flight.objects.filter(live=True).select_related():
        # Check for hard stopped flights
        if flight.hard_stop and flight.end_date <= cutoff.date():
            log.info("Flight %s is being hard stopped.", flight)
            value_remaining = round(flight.value_remaining(), 2)
            flight_url = generate_absolute_url(flight.get_absolute_url())

            # Send an internal notification about this flight being hard stopped.
            slack_message(
                "adserver/slack/generic-message.slack",
                {
                    "text": f"Flight {flight.name} was hard stopped. There was ${value_remaining:.2f} value remaining. {flight_url}"
                },
            )

            # Mark the flight as no longer live. It was hard stopped
            flight.live = False
            flight.save()

            # Store the change reason in the history
            update_change_reason(
                flight, f"Hard stopped with ${value_remaining} value remaining."
            )

            completed_flights_by_advertiser[flight.campaign.advertiser.slug].append(
                flight
            )
        elif (
            flight.clicks_remaining() == 0
            and flight.views_remaining() == 0
            and AdImpression.objects.filter(
                date__gte=cutoff, advertisement__flight=flight
            ).exists()
        ):
            log.info("Flight %s finished in the last day.", flight)

            # Send an internal notification about this flight
            slack_message(
                "adserver/slack/flight-complete.slack",
                {
                    "flight": flight,
                    "flight_url": generate_absolute_url(flight.get_absolute_url()),
                },
            )

            # Mark the flight as no longer live. It is complete
            flight.live = False
            flight.save()

            completed_flights_by_advertiser[flight.campaign.advertiser.slug].append(
                flight
            )

    # Send notification to advertiser - one email even if multiple flights finished
    if settings.FRONT_ENABLED:
        site = get_current_site(request=None)

        for (
            advertiser_slug,
            completed_flights,
        ) in completed_flights_by_advertiser.items():
            advertiser = Advertiser.objects.get(slug=advertiser_slug)

            to_addresses = [
                u.email
                for u in advertiser.user_set.all()
                if u.notify_on_completed_flights
            ]

            if not to_addresses:
                log.debug("No recipients for the wrapup email. Skipping...")
                continue

            context = {
                "advertiser": advertiser,
                "site": site,
                # Just the flights completed today
                "completed_flights": completed_flights,
                "current_flights": [
                    f
                    for f in Flight.objects.filter(campaign__advertiser=advertiser)
                    if f.state == FLIGHT_STATE_CURRENT
                ],
                "upcoming_flights": [
                    f
                    for f in Flight.objects.filter(campaign__advertiser=advertiser)
                    if f.state == FLIGHT_STATE_UPCOMING
                ],
            }

            with mail.get_connection(
                settings.FRONT_BACKEND,
                sender_name=f"{site.name} Flight Tracker",
            ) as connection:
                message = mail.EmailMessage(
                    _("Advertising flight wrapup - %(name)s") % {"name": site.name},
                    render_to_string("adserver/email/flight_wrapup.html", context),
                    from_email=settings.DEFAULT_FROM_EMAIL,  # Front doesn't use this
                    to=to_addresses,
                    connection=connection,
                )
                message.send()


@app.task()
def notify_of_publisher_changes(difference_threshold=0.25, min_views=10_000):
    """
    Send a notification when a publisher's main metrics change week to week.

    :param difference_threshold: Notify of differences larger than this (0.25 = 25%)
    :param min_views: Don't notify unless there's at least this many views (between both weeks)
    """
    a_week_ago = get_ad_day() - datetime.timedelta(days=7)
    two_weeks_ago = a_week_ago - datetime.timedelta(days=7)

    for publisher in Publisher.objects.filter(allow_paid_campaigns=True):
        # Generate a report for the last week
        queryset = AdImpression.objects.filter(
            date__gte=a_week_ago,
            publisher=publisher,
            advertisement__flight__campaign__campaign_type=PAID_CAMPAIGN,
        )
        last_week_report = PublisherReport(queryset)
        last_week_report.generate()

        # Generate the previous week for comparison
        queryset = AdImpression.objects.filter(
            date__gte=two_weeks_ago,
            date__lte=a_week_ago,
            publisher=publisher,
            advertisement__flight__campaign__campaign_type=PAID_CAMPAIGN,
        )
        previous_week_report = PublisherReport(queryset)
        previous_week_report.generate()

        for metric in ("revenue",):
            total_views = (
                last_week_report.total["views"] + previous_week_report.total["views"]
            )
            last_week_value = last_week_report.total[metric]
            previous_week_value = previous_week_report.total[metric]
            if last_week_value > 0 and previous_week_value > 0:
                metric_diff = abs((last_week_value / previous_week_value) - 1)
                perc_diff = calculate_percent_diff(last_week_value, previous_week_value)
                if metric_diff > difference_threshold and total_views >= min_views:
                    log.info(
                        "Publisher %s: %s was %s last week and %s the previous week.",
                        publisher,
                        metric,
                        last_week_value,
                        previous_week_value,
                    )

                    # Send notification to Slack about this publisher
                    slack_message(
                        "adserver/slack/publisher-metric.slack",
                        {
                            "publisher": publisher,
                            "metric": metric,
                            "last_week_value": last_week_value,
                            "previous_week_value": previous_week_value,
                            "percent_diff": perc_diff,
                            "report_url": generate_absolute_url(
                                publisher.get_absolute_url()
                            ),
                        },
                    )


@app.task()
def disable_inactive_publishers(days=60, draft_only=False, dry_run=False):
    """Disable publishers who haven't had a paid impression in the specified `days`."""
    if days < 30:
        # Prevent the misstep where days is too short and many publishers are marked inactive
        log.warning("Disabling publishers over too short a timeframe. Task stopped.")
        return

    threshold = get_ad_day() - datetime.timedelta(days=days)
    site = get_current_site(request=None)

    for publisher in Publisher.objects.filter(
        allow_paid_campaigns=True, created__lt=threshold
    ):
        if not PublisherPaidImpression.objects.filter(
            publisher=publisher, date__gte=threshold
        ).exists():
            log.info(
                "Disabling paid ad approval on %s who has not shown a paid ad in at least %s days...",
                publisher,
                days,
            )
            if dry_run:
                log.info("- Not actually disabling due to dry run")
                continue

            publisher.allow_paid_campaigns = False
            publisher.save()

            slack_message(
                "adserver/slack/generic-message.slack",
                {
                    "text": f"Disabled paid ad approval on {publisher} who has not shown a paid ad in at least {days} days."
                },
            )

            to_addresses = [u.email for u in publisher.user_set.all()]
            context = {
                "publisher": publisher,
                "days": days,
                "site": site,
            }

            if settings.FRONT_ENABLED and to_addresses:
                with mail.get_connection(
                    settings.FRONT_BACKEND,
                    sender_name=f"{site.name} Admins",
                ) as connection:
                    message = mail.EmailMessage(
                        _("Publisher account deactivated - %(name)s")
                        % {"name": site.name},
                        render_to_string(
                            "adserver/email/publisher-inactive.html", context
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,  # Front doesn't use this
                        to=to_addresses,
                        connection=connection,
                    )

                    if draft_only:
                        # Make this a draft instead of just sending it directly if specified
                        message.draft = True

                    message.send()


@app.task()
def update_flight_traffic_fill():
    """Update a cached value on each paid flight with its fill rate by region/geo/publisher."""
    max_objects = 20
    threshold = 0.01  # Nothing below this percent will be aggregated

    log.info("Updating flight traffic fill")

    # Update the traffic fill rates for each publisher/region/country for each flight
    for flight in Flight.objects.filter(
        live=True, campaign__campaign_type=PAID_CAMPAIGN, total_views__gt=0
    ):
        publisher_traffic_fill = {}
        country_traffic_fill = {}
        region_traffic_fill = {}

        # Publisher (fast)
        for imp in (
            AdImpression.objects.using(settings.REPLICA_SLUG)
            .filter(advertisement__flight=flight)
            .values(
                "publisher__slug",
            )
            .annotate(
                publisher_views=Sum("views"),
            )
            .order_by("-publisher_views")[:max_objects]
        ):
            publisher_slug = imp["publisher__slug"]
            publisher_percentage = imp["publisher_views"] / flight.total_views
            if publisher_percentage >= threshold:
                publisher_traffic_fill[publisher_slug] = publisher_percentage

        # Region (slower)
        for imp in (
            RegionImpression.objects.using(settings.REPLICA_SLUG)
            .filter(advertisement__flight=flight)
            .values(
                "region",
            )
            .annotate(
                region_views=Sum("views"),
            )
            .order_by("-region_views")[:max_objects]
        ):
            region = imp["region"]
            region_percentage = imp["region_views"] / flight.total_views
            if region_percentage >= threshold:
                region_traffic_fill[region] = region_percentage

        # Country (slowest)
        for imp in (
            GeoImpression.objects.using(settings.REPLICA_SLUG)
            .filter(advertisement__flight=flight)
            .values(
                "country",
            )
            .annotate(
                country_views=Sum("views"),
            )
            .order_by("-country_views")[:max_objects]
        ):
            country_code = imp["country"]
            country_percentage = imp["country_views"] / flight.total_views
            if country_percentage >= threshold:
                country_traffic_fill[country_code] = country_percentage

        # Grab the flight from the DB again in case the object has changed
        flight.refresh_from_db()
        if not flight.traffic_fill:
            flight.traffic_fill = {}
        flight.traffic_fill["publishers"] = publisher_traffic_fill
        flight.traffic_fill["countries"] = country_traffic_fill
        flight.traffic_fill["regions"] = region_traffic_fill
        flight.save()

    log.info("Completed updating flight traffic fill")


@app.task()
def run_publisher_importers():
    """
    Run a sync task for all the importers from our various publishers.

    This is done nightly to ensure imported data is up to date.
    """
    # PSF is the only importer for now..
    psf.run_import(sync=True)
