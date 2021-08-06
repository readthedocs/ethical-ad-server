"""Celery tasks for the ad server."""
import datetime
import json
import logging
from collections import defaultdict

from celery.utils.iso8601 import parse_iso8601
from django.conf import settings
from django.db.models import Count
from django.db.models import F
from django.utils.timezone import is_naive
from django.utils.timezone import utc
from django_slack import slack_message

from .constants import CLICKS
from .constants import IMPRESSION_TYPES
from .constants import OFFERS
from .constants import PAID_CAMPAIGN
from .constants import VIEWS
from .models import AdImpression
from .models import Flight
from .models import GeoImpression
from .models import KeywordImpression
from .models import Offer
from .models import PlacementImpression
from .models import Publisher
from .models import RegionImpression
from .models import RegionTopicImpression
from .models import UpliftImpression
from .regiontopics import africa
from .regiontopics import backend_web
from .regiontopics import blockchain
from .regiontopics import data_science
from .regiontopics import devops
from .regiontopics import eu_aus_nz
from .regiontopics import frontend_web
from .regiontopics import game_dev
from .regiontopics import latin_america
from .regiontopics import python
from .regiontopics import security_privacy
from .regiontopics import us_ca
from .regiontopics import wider_apac
from .reports import PublisherReport
from .utils import calculate_percent_diff
from .utils import generate_absolute_url
from .utils import get_ad_day
from config.celery_app import app

log = logging.getLogger(__name__)  # noqa


def _get_day(day):
    """Get the start and end time with support for celery-encoded strings, dates, and datetimes."""
    start_date = get_ad_day()
    if day:
        log.info("Got day: %s", day)
        if not isinstance(day, (datetime.datetime, datetime.date)):
            log.info("Converting day from string")
            day = parse_iso8601(day)
        start_date = day.replace(hour=0, minute=0, second=0, microsecond=0)
        if is_naive(start_date):
            start_date = utc.localize(start_date)
    end_date = start_date + datetime.timedelta(days=1)

    return (start_date, end_date)


def _default_filters(impression_type, start_date, end_date):
    """Filter the queryset by date and impression type."""
    queryset = Offer.objects.filter(
        date__gte=start_date,
        date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
        # is_refunded=False,  # This causes the query to be a filtered index and is much slower
    )

    if impression_type == CLICKS:
        queryset = queryset.filter(clicked=True)
    elif impression_type == VIEWS:
        queryset = queryset.filter(viewed=True)
    elif impression_type == OFFERS:
        queryset = queryset.filter(advertisement__isnull=False)

    return queryset


@app.task()
def daily_update_geos(day=None, geo=True, region=True):
    """
    Update the Geo & region index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = _get_day(day)

    if not geo and not region:
        log.error("geo or region required, please pass one as True")
        return

    if geo:
        log.info("Updating GeoImpressions for %s-%s", start_date, end_date)

    if region:
        log.info("Updating RegionImpressions for %s-%s", start_date, end_date)
        # Delete all previous Region impressions
        RegionImpression.objects.filter(
            date__gte=start_date,
            date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
        ).delete()

    for impression_type in IMPRESSION_TYPES:
        queryset = _default_filters(impression_type, start_date, end_date)
        value_list = ["advertisement", "country"]
        if geo:
            value_list.append("publisher")
        for values in (
            queryset.values(*value_list)
            .annotate(total=Count("country"))
            .filter(total__gt=0)
            .order_by("-total")
        ):
            country = values["country"]
            if geo:
                impression, _ = GeoImpression.objects.get_or_create(
                    publisher_id=values["publisher"],
                    advertisement_id=values["advertisement"],
                    country=country,
                    date=start_date,
                )
                GeoImpression.objects.filter(pk=impression.pk).update(
                    **{impression_type: values["total"]}
                )

            if region:

                if country in us_ca:
                    _region = "us-ca"
                elif country in eu_aus_nz:
                    _region = "eu-aus-nz"
                elif country in wider_apac:
                    _region = "wider-apac"
                elif country in latin_america:
                    _region = "latin-america"
                elif country in africa:
                    _region = "africa"
                else:
                    _region = "global"

                impression, _ = RegionImpression.objects.get_or_create(
                    advertisement_id=values["advertisement"],
                    region=_region,
                    date=start_date,
                )
                RegionImpression.objects.filter(pk=impression.pk).update(
                    **{impression_type: F(impression_type) + values["total"]}
                )


@app.task()
def daily_update_placements(day=None):
    """
    Update the Placement index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = _get_day(day)

    log.info("Updating PlacementImpressions for %s-%s", start_date, end_date)

    for impression_type in IMPRESSION_TYPES:
        queryset = _default_filters(impression_type, start_date, end_date)
        for values in (
            queryset.values("publisher", "advertisement", "div_id", "ad_type_slug")
            .annotate(total=Count("div_id"))
            .filter(total__gt=0)
            .filter(publisher__record_placements=True)
            .exclude(div_id__regex=r"(rtd-\w{4}|ad_\w{4}).*")
            .order_by("-total")
        ):

            impression, _ = PlacementImpression.objects.get_or_create(
                publisher_id=values["publisher"],
                advertisement_id=values["advertisement"],
                div_id=values["div_id"],
                ad_type_slug=values["ad_type_slug"],
                date=start_date,
            )
            PlacementImpression.objects.filter(pk=impression.pk).update(
                **{impression_type: values["total"]}
            )


@app.task()
def daily_update_impressions(day=None):
    """
    Update the AdImpression index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = _get_day(day)

    log.info("Updating AdImpressions for %s-%s", start_date, end_date)

    for impression_type in IMPRESSION_TYPES:
        queryset = _default_filters(impression_type, start_date, end_date)

        for values in (
            queryset.values("publisher", "advertisement")
            # This needs to be publisher and not advertisement to gets decisions properly
            .annotate(total=Count("publisher"))
            .filter(total__gt=0)
            .order_by("-total")
        ):

            impression, _ = AdImpression.objects.get_or_create(
                publisher_id=values["publisher"],
                advertisement_id=values["advertisement"],
                date=start_date,
            )
            AdImpression.objects.filter(pk=impression.pk).update(
                **{impression_type: values["total"]}
            )


@app.task()
def daily_update_keywords(day=None):
    """
    Update the KeywordImpression index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = _get_day(day)

    log.info("Updating KeywordImpression for %s-%s", start_date, end_date)

    # Remove all old keyword impressions, because they are cumulative
    KeywordImpression.objects.filter(
        date__gte=start_date,
        date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
    ).delete()

    for impression_type in IMPRESSION_TYPES:
        queryset = _default_filters(impression_type, start_date, end_date)

        for values in (
            queryset.values("publisher", "advertisement", "keywords")
            .annotate(total=Count("keywords"))
            .filter(total__gt=0)
            .order_by("-total")
            .values(
                "publisher",
                "advertisement",
                "keywords",
                "advertisement__flight__targeting_parameters",
                "total",
            )
        ):
            if not (
                values["keywords"]
                and values["advertisement__flight__targeting_parameters"]
            ):
                continue

            keywords = json.loads(values["keywords"])
            publisher_keywords = set(keywords)

            flight_targeting = json.loads(
                values["advertisement__flight__targeting_parameters"]
            )
            flight_keywords = set(flight_targeting.get("include_keywords", {}))

            matched_keywords = publisher_keywords & flight_keywords
            for keyword in matched_keywords:
                impression, _ = KeywordImpression.objects.get_or_create(
                    date=start_date,
                    publisher_id=values["publisher"],
                    advertisement_id=values["advertisement"],
                    keyword=keyword,
                )
                # These are a Sum because we can't query for specific keywords from Postgres,
                # so a specific publisher and advertisement set could return the same keyword:
                # ['python', 'django'] and ['python, 'flask'] both are `python` in this case.
                KeywordImpression.objects.filter(pk=impression.pk).update(
                    **{impression_type: F(impression_type) + values["total"]}
                )


@app.task()
def daily_update_regiontopic(day=None):  # pylint: disable=too-many-branches
    """
    Update the RegionTopicImpression index each day.

    Each data point will have one region, but multiple possible topics.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = _get_day(day)

    log.info("Updating RegionTopic's for %s-%s", start_date, end_date)

    # Remove all old impressions, because they are cumulative
    RegionTopicImpression.objects.filter(
        date__gte=start_date,
        date__lt=end_date,
    ).delete()

    for impression_type in IMPRESSION_TYPES:
        queryset = _default_filters(impression_type, start_date, end_date)

        topic_mapping = defaultdict(int)

        for values in (
            queryset.values("keywords", "country")
            .annotate(total=Count("country"))
            .filter(total__gt=0)
            .order_by("-total")
            .values(
                "keywords",
                "country",
                "total",
            )
        ):
            if not (values["keywords"] and values["country"]):
                continue

            keywords = json.loads(values["keywords"])
            country = values["country"]
            publisher_keywords = set(keywords)

            topics = set()
            for keyword in publisher_keywords:
                if keyword in data_science:
                    topic = "data-science"
                elif keyword in backend_web:
                    topic = "backend-web"
                elif keyword in frontend_web:
                    topic = "frontend-web"
                elif keyword in security_privacy:
                    topic = "security-privacy"
                elif keyword in devops:
                    topic = "devops"
                elif keyword in python:
                    topic = "python"
                elif keyword in blockchain:
                    topic = "blockchain"
                elif keyword in game_dev:
                    topic = "game-dev"
                else:
                    continue

                topics.add(topic)

            if country in us_ca:
                region = "us-ca"
            elif country in eu_aus_nz:
                region = "eu-aus-nz"
            elif country in wider_apac:
                region = "wider-apac"
            elif country in latin_america:
                region = "latin-america"
            elif country in africa:
                region = "africa"
            else:
                region = "global"

            # Aggregate data into topic_mapping to save doing queries until we have everything counted
            # This is important because we can't query on keywords, so we have a lot of records that increment
            # the total count on the region & topic.
            for topic in topics:
                topic_mapping[f"{region}:{topic}"] += values["total"]

        for region_topic, value in topic_mapping.items():
            region, topic = region_topic.split(":")
            impression, _ = RegionTopicImpression.objects.get_or_create(
                date=start_date,
                region=region,
                topic=topic,
            )
            # These are a Sum because we can't query for specific keywords from Postgres,
            # so a specific publisher and advertisement set could return the same keyword:
            # ['python', 'django'] and ['python, 'flask'] both are `python` in this case.
            RegionTopicImpression.objects.filter(pk=impression.pk).update(
                **{impression_type: F(impression_type) + value}
            )


@app.task()
def daily_update_uplift(day=None):
    """
    Generate the daily index of UpliftImpressions.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = _get_day(day)

    log.info("Updating uplift for %s-%s", start_date, end_date)

    for impression_type in IMPRESSION_TYPES:
        queryset = _default_filters(impression_type, start_date, end_date)

        for values in (
            queryset.values("publisher", "advertisement")
            .annotate(total=Count("uplifted"))
            .filter(total__gt=0)
            .order_by("-total")
            .values("publisher", "advertisement", "total")
        ):

            impression, _ = UpliftImpression.objects.get_or_create(
                publisher_id=values["publisher"],
                advertisement_id=values["advertisement"],
                date=start_date,
            )
            UpliftImpression.objects.filter(pk=impression.pk).update(
                **{impression_type: values["total"]}
            )


@app.task()
def update_previous_day_reports(day=None):
    """
    Complete all report data for the previous day.

    :arg day: An optional datetime object representing a day.
    """
    start_date, _ = _get_day(day)

    # Do the previous day now that the day is complete
    start_date -= datetime.timedelta(days=1)

    # Do all reports
    daily_update_geos(start_date)
    daily_update_placements(start_date)
    daily_update_impressions(start_date)
    daily_update_keywords(start_date)
    daily_update_uplift(start_date)
    daily_update_regiontopic(start_date)


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

    for publisher in Publisher.objects.all():
        queryset = AdImpression.objects.filter(
            date__gte=sample_cutoff,
            publisher=publisher,
            advertisement__flight__campaign__campaign_type=PAID_CAMPAIGN,
        )
        report = PublisherReport(queryset)
        report.generate()

        publisher.sampled_ctr = report.total["ctr"]
        publisher.save()


@app.task()
def notify_of_completed_flights():
    """Send a notification about flights which completed in the last day."""
    cutoff = get_ad_day() - datetime.timedelta(days=1)
    for flight in Flight.objects.filter(live=True).filter():
        if (
            flight.clicks_remaining() == 0
            and flight.views_remaining() == 0
            and AdImpression.objects.filter(
                date__gte=cutoff,
                advertisement__flight=flight,
            ).exists()
        ):
            log.info("Flight %s finished in the last day.", flight)

            # Send notification about this flight
            if settings.SLACK_TOKEN:
                slack_message(
                    "adserver/slack/flight-complete.slack",
                    {
                        "flight": flight,
                        "flight_url": generate_absolute_url(flight.get_absolute_url()),
                    },
                )


@app.task()
def notify_of_publisher_changes(difference_threshold=0.25, min_views=1000):
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

        for metric in ("views", "ctr"):
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
                    if settings.SLACK_TOKEN:
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
