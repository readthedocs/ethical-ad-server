"""Mixins for advertiser and publisher views."""

import logging

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.paginator import Paginator
from django.db import connection
from django.db import models
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from .constants import ALL_CAMPAIGN_TYPES
from .constants import CAMPAIGN_TYPES
from .models import Advertiser
from .models import Publisher
from .utils import COUNTRY_DICT


log = logging.getLogger(__name__)  # noqa


class StaffUserMixin(UserPassesTestMixin):
    """Mixin requiring staff access."""

    def test_func(self):
        return self.request.user.is_staff


class AdvertiserAccessMixin:
    """Mixin for checking advertiser access that works with the ``UserPassesTestMixin``."""

    advertiser_slug_parameter = "advertiser_slug"

    def test_func(self):
        """The user must have access on the advertiser or be staff."""
        if self.request.user.is_anonymous:
            return False

        advertiser = get_object_or_404(
            Advertiser, slug=self.kwargs[self.advertiser_slug_parameter]
        )
        return (
            self.request.user.is_staff
            or advertiser in self.request.user.advertisers.all()
        )


class PublisherAccessMixin:
    """Mixin for checking publisher access that works with the ``UserPassesTestMixin``."""

    publisher_slug_parameter = "publisher_slug"

    def test_func(self):
        """The user must have access on the publisher or be staff."""
        if self.request.user.is_anonymous:
            return False

        publisher = get_object_or_404(
            Publisher, slug=self.kwargs[self.publisher_slug_parameter]
        )
        return (
            self.request.user.is_staff
            or publisher in self.request.user.publishers.all()
        )


class AdvertisementValidateLinkMixin:
    """
    Mixin for validating the landing page returns a 200.

    Raises a warning otherwise.
    Should only be used on a FormView.
    """

    TIMEOUT = 2  # seconds (2 seconds for reading, 2 seconds for DNS)

    VALIDATE_LINK_MESSAGES = {
        "error": _(
            "Your link returned an error with status %s. "
            "Double check that your landing page is live. "
            "Occasionally, landing pages block automated access "
            "and that can result in a false positive."
        ),
        "redirect": _(
            "Your link redirected to a page (%s) that did successfully load. "
            "Double check that this redirect is intentional."
        ),
        "other_error": _(
            "There was an error validating your landing page. "
            "Double check that the landing page loads correctly."
        ),
    }

    def form_valid(self, form):
        result = super().form_valid(form)
        ad = self.object

        try:
            resp = requests.get(ad.link, timeout=self.TIMEOUT)

            if not resp.ok:
                messages.warning(
                    self.request,
                    self.VALIDATE_LINK_MESSAGES["error"] % resp.status_code,
                )
            elif resp.history:
                messages.warning(
                    self.request, self.VALIDATE_LINK_MESSAGES["redirect"] % resp.url
                )
        except requests.exceptions.RequestException:
            messages.warning(self.request, self.VALIDATE_LINK_MESSAGES["other_error"])

        return result


class ReportQuerysetMixin:
    """Mixin for getting a queryset of advertiser report data."""

    # Subclasses must define one of these
    impression_model = None

    def get_queryset(self, **kwargs):
        """Get the queryset (from ``impression_model``) used to generate the report."""
        queryset = self.impression_model.objects.all()

        if "start_date" in kwargs and kwargs["start_date"]:
            queryset = queryset.filter(date__gte=kwargs["start_date"])
        if "end_date" in kwargs and kwargs["end_date"]:
            queryset = queryset.filter(date__lte=kwargs["end_date"])

        # Advertiser filters
        if "advertiser" in kwargs and kwargs["advertiser"]:
            if isinstance(kwargs["advertiser"], Advertiser):
                queryset = queryset.filter(
                    advertisement__flight__campaign__advertiser=kwargs["advertiser"]
                )
            else:
                queryset = queryset.filter(
                    advertisement__flight__campaign__advertiser__slug=kwargs[
                        "advertiser"
                    ]
                )
        if "flight" in kwargs and kwargs["flight"]:
            queryset = queryset.filter(advertisement__flight=kwargs["flight"])

        # Publisher filters
        if "publisher" in kwargs and kwargs["publisher"]:
            if isinstance(kwargs["publisher"], Publisher):
                queryset = queryset.filter(publisher=kwargs["publisher"])
            else:
                queryset = queryset.filter(publisher__slug=kwargs["publisher"])
        if "publishers" in kwargs and kwargs["publishers"]:
            queryset = queryset.filter(publisher__in=kwargs["publishers"])
        if "campaign_type" in kwargs and kwargs["campaign_type"] in ALL_CAMPAIGN_TYPES:
            queryset = queryset.filter(
                advertisement__flight__campaign__campaign_type=kwargs["campaign_type"]
            )
        if "region" in kwargs and kwargs["region"]:
            queryset = queryset.filter(region=kwargs["region"])
        if "topic" in kwargs and kwargs["topic"]:
            queryset = queryset.filter(topic=kwargs["topic"])

        return queryset


class GeoReportMixin:
    """Provide geo report functionality. MUST be used with BaseReportView."""

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset(**kwargs)

        if "country" in kwargs and kwargs["country"]:
            queryset = queryset.filter(country__iexact=kwargs["country"])

        # Only filter this if we didn't pass a specific country
        elif "countries" in kwargs and kwargs["countries"]:
            queryset = queryset.filter(country__in=kwargs["countries"])

        return queryset

    def get_country_options(self, queryset):
        # The order_by here is to enable distinct to work
        # https://docs.djangoproject.com/en/dev/ref/models/querysets/#distinct
        country_list = (
            queryset.values_list("country", flat=True)
            .annotate(total_views=models.Sum("views"))
            .order_by("-total_views")
            .distinct()[: self.LIMIT]
        )

        return ((cc, COUNTRY_DICT.get(cc, "Unknown")) for cc in country_list)

    def get_country_name(self, country):
        return COUNTRY_DICT.get(country)


class KeywordReportMixin:
    """Provide keyword functionality. MUST be used with BaseReportView."""

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset(**kwargs)

        if "keyword" in kwargs and kwargs["keyword"]:
            queryset = queryset.filter(keyword__iexact=kwargs["keyword"])
        # Only filter this if we didn't pass a specific country
        elif "keywords" in kwargs and kwargs["keywords"]:
            queryset = queryset.filter(keywords__in=kwargs["keywords"])

        return queryset

    def get_keyword_options(self, queryset):
        # The order_by here is to enable distinct to work
        # https://docs.djangoproject.com/en/dev/ref/models/querysets/#distinct
        keyword_options = (
            queryset.values_list("keyword", flat=True)
            .annotate(total_views=models.Sum("views"))
            .order_by("-total_views")
            .distinct()[: self.LIMIT]
        )

        return keyword_options


class AllReportMixin:
    """A mixin that handles the primary "view" logic for staff reports."""

    def get_context_data(self, **kwargs):
        """Set the base data needed for all reports."""
        context = super().get_context_data(**kwargs)

        sort = self.request.GET.get("sort", "")
        force_revshare = self.request.GET.get("force_revshare", self.force_revshare)

        order = None
        index = None
        filtered = []

        # Handle filtering a larger subset of reports as needed
        # TODO: Backport similar logic to the base report class?
        kwargs = {}
        for arg in ["keyword", "country", "publisher", "region", "topic"]:
            if arg in self.request.GET and self.request.GET[arg]:
                kwargs[arg] = self.request.GET[arg]
                filtered.append(arg)
        log.debug("Filtering report by %s", kwargs)

        queryset = self.get_queryset(
            start_date=context["start_date"],
            end_date=context["end_date"],
            campaign_type=context["campaign_type"],
            **kwargs,
        )

        # The FILTER_COUNT is required for indexes that have multiple indexes (region & topic),
        # so that we can properly show the values for a single-index filter (eg. only by region or topic)
        if len(filtered) >= self.FILTER_COUNT:
            # Sort by date when filtering a specific value,
            # otherwise handle sorting via the users input
            order = "-date"
            index = "date"
        elif sort:
            order = f"-{sort}"

        report = self.report(
            queryset,
            max_results=None,
            force_revshare=force_revshare,
            order=order,
            index=index,
            export=self.export,
        )
        report.generate()
        sort_options = report.total.keys()

        context.update(
            {
                "report": report,
                "campaign_types": CAMPAIGN_TYPES,
                "sort": sort,
                "sort_options": sort_options,
                "export_url": self.get_export_url(),
                "filtered": filtered,
            }
        )

        return context


class EstimatedCountPaginator(Paginator):
    """
    Paginator that gives only an estimated count based on DB statistics..

    This only works for PostgreSQL. Other database engines always return the full count.
    """

    @cached_property
    def count(self):
        if (
            settings.DEBUG
            or "postgresql" not in settings.DATABASES["default"]["ENGINE"]
        ):
            return super().count

        query = self.object_list.query

        # We set the timeout in a db transaction to prevent it from
        # affecting other transactions.
        with connection.cursor() as cursor:
            # This is postgres specific
            cursor.execute(
                "SELECT reltuples FROM pg_class WHERE relname = %s",
                [query.model._meta.db_table],
            )
            return int(cursor.fetchone()[0])
