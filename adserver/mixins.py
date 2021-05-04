"""Mixins for advertiser and publisher views."""
from django.conf import settings
from django.core.paginator import Paginator
from django.db import connection
from django.db import models
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property
from django_countries import countries

from .constants import ALL_CAMPAIGN_TYPES
from .constants import CAMPAIGN_TYPES
from .models import Advertiser
from .models import Publisher


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
            queryset = queryset.filter(
                advertisement__flight__campaign__advertiser=kwargs["advertiser"]
            )
        if "flight" in kwargs and kwargs["flight"]:
            queryset = queryset.filter(advertisement__flight=kwargs["flight"])

        # Publisher filters
        if "publisher" in kwargs and kwargs["publisher"]:
            queryset = queryset.filter(publisher=kwargs["publisher"])
        if "publishers" in kwargs and kwargs["publishers"]:
            queryset = queryset.filter(publisher__in=kwargs["publishers"])
        if "campaign_type" in kwargs and kwargs["campaign_type"] in ALL_CAMPAIGN_TYPES:
            queryset = queryset.filter(
                advertisement__flight__campaign__campaign_type=kwargs["campaign_type"]
            )

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
        countries_dict = dict(countries)

        # The order_by here is to enable distinct to work
        # https://docs.djangoproject.com/en/dev/ref/models/querysets/#distinct
        country_list = (
            queryset.values_list("country", flat=True)
            .annotate(total_views=models.Sum("views"))
            .order_by("-total_views")
            .distinct()[: self.LIMIT]
        )

        return ((cc, countries_dict.get(cc, "Unknown")) for cc in country_list)

    def get_country_name(self, country):
        countries_dict = dict(countries)
        return countries_dict.get(country)


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
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        sort = self.request.GET.get("sort", "")
        force_revshare = self.request.GET.get("force_revshare", self.force_revshare)

        arg_defined = False
        kwargs = {}
        for arg in ["keyword", "geo", "publisher"]:
            if arg in self.request.GET:
                kwargs[arg] = self.request.GET[arg]
                arg_defined = True

        queryset = self.get_queryset(
            start_date=context["start_date"],
            end_date=context["end_date"],
            campaign_type=context["campaign_type"],
            **kwargs,
        )

        report = self.report(
            queryset,
            max_results=None,
            force_revshare=force_revshare,
            order=sort if sort else None,
            index="date" if arg_defined else None,
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
