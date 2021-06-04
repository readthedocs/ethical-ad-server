"""Celery tasks for the ad server."""
import datetime
import json
import logging

from celery.utils.iso8601 import parse_iso8601
from django.db.models import Count
from django.db.models import F
from django.utils.timezone import is_naive
from django.utils.timezone import utc

from .constants import CLICKS
from .constants import IMPRESSION_TYPES
from .constants import OFFERS
from .constants import VIEWS
from .models import AdImpression
from .models import GeoImpression
from .models import KeywordImpression
from .models import Offer
from .models import PlacementImpression
from .models import RegionTopicImpression
from .models import UpliftImpression
from .regiontopics import africa
from .regiontopics import backend_web
from .regiontopics import blockchain
from .regiontopics import data_science
from .regiontopics import devops
from .regiontopics import eu_aus_nz
from .regiontopics import exclude
from .regiontopics import frontend_web
from .regiontopics import game_dev
from .regiontopics import latin_america
from .regiontopics import python
from .regiontopics import security_privacy
from .regiontopics import us_ca
from .regiontopics import wider_apac
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
def daily_update_geos(day=None):
    """
    Update the Geo index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = _get_day(day)

    log.info("Updating GeoImpressions for %s-%s", start_date, end_date)

    for impression_type in IMPRESSION_TYPES:
        queryset = _default_filters(impression_type, start_date, end_date)
        for values in (
            queryset.values("publisher", "advertisement", "country")
            .annotate(total=Count("country"))
            .filter(total__gt=0)
            .order_by("-total")
        ):
            impression, _ = GeoImpression.objects.get_or_create(
                publisher_id=values["publisher"],
                advertisement_id=values["advertisement"],
                country=values["country"],
                date=start_date,
            )
            GeoImpression.objects.filter(pk=impression.pk).update(
                **{impression_type: values["total"]}
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
def daily_update_regiontopic(day=None):
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

    for impression_type in ["views"]:
        queryset = _default_filters(impression_type, start_date, end_date)

        unsold = {}
        no_keywords = {}

        for values in (
            queryset.values("publisher", "advertisement", "keywords", "country")
            .annotate(total=Count("country"))
            .filter(total__gt=0)
            .order_by("-total")
            .values(
                "publisher",
                "advertisement",
                "keywords",
                "country",
                "advertisement__flight__targeting_parameters",
                "total",
            )
        ):
            if not (
                values["keywords"]
                and values["country"]
                and values["advertisement__flight__targeting_parameters"]
            ):
                continue

            keywords = json.loads(values["keywords"])
            country = values["country"]
            publisher_keywords = set(keywords)

            flight_targeting = json.loads(
                values["advertisement__flight__targeting_parameters"]
            )
            flight_keywords = set(flight_targeting.get("include_keywords", {}))

            matched_keywords = publisher_keywords & flight_keywords

            topics = set()
            for keyword in matched_keywords:
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
                    log.debug(f"Sold keyword not in topic: {keyword}")
                    topic = "other"
                    if keyword in unsold:
                        unsold[keyword] += 1
                    else:
                        unsold[keyword] = 1
                topics.add(topic)

            if not matched_keywords:
                # No matched keywords
                for keyword in publisher_keywords:
                    log.debug(f"Untargeted ad for keyword: {keyword}")
                    if keyword in no_keywords:
                        no_keywords[keyword] += 1
                    else:
                        no_keywords[keyword] = 1

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

            for topic in topics:
                impression, _ = RegionTopicImpression.objects.get_or_create(
                    date=start_date,
                    publisher_id=values["publisher"],
                    advertisement_id=values["advertisement"],
                    region=region,
                    topic=topic,
                )
                # These are a Sum because we can't query for specific keywords from Postgres,
                # so a specific publisher and advertisement set could return the same keyword:
                # ['python', 'django'] and ['python, 'flask'] both are `python` in this case.
                RegionTopicImpression.objects.filter(pk=impression.pk).update(
                    **{impression_type: F(impression_type) + values["total"]}
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
