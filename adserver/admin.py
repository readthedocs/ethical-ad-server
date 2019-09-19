"""Django admin configuration for the ad server."""
from django.contrib import admin
from django.db import models
from django.template.loader import render_to_string
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .forms import FlightForm
from .models import AdImpression
from .models import AdType
from .models import Advertisement
from .models import Advertiser
from .models import Campaign
from .models import Click
from .models import Flight
from .models import Publisher
from .models import View
from .utils import calculate_ctr
from .utils import calculate_ecpm


class RemoveDeleteMixin:

    """Removes the ability to delete this model from the admin."""

    def get_actions(self, request):
        actions = super(RemoveDeleteMixin, self).get_actions(request)
        if "delete_selected" in actions:
            del actions["delete_selected"]
        return actions

    def has_delete_permission(self, request, obj=None):
        return False


class PublisherAdmin(RemoveDeleteMixin, admin.ModelAdmin):

    """Django admin configuration for publishers."""

    prepopulated_fields = {"slug": ("name",)}


class AdvertiserAdmin(RemoveDeleteMixin, admin.ModelAdmin):

    """Django admin configuration for advertisers."""

    prepopulated_fields = {"slug": ("name",)}


class AdTypeAdmin(admin.ModelAdmin):

    """Django admin configuration for ad types."""

    model = AdType
    save_as = True
    prepopulated_fields = {"slug": ("name",)}
    list_display = ("name", "publisher")
    list_select_related = ("publisher",)
    search_fields = ("name", "slug", "publisher__name", "publisher__slug")


class AdvertisementAdmin(RemoveDeleteMixin, admin.ModelAdmin):

    """Django admin configuration for advertisements."""

    model = Advertisement
    save_as = True
    prepopulated_fields = {"slug": ("name",)}
    list_display = (
        "display_image",
        "name",
        "slug",
        "flight",
        "ad_type",
        "live",
        "ad_report",
        "num_views",
        "num_clicks",
        "ctr",
        "ecpm",
    )
    list_display_links = ("name",)
    list_select_related = ("flight", "flight__campaign", "ad_type")
    list_filter = (
        "live",
        "flight__campaign__campaign_type",
        "ad_type",
        "flight__campaign",
    )
    list_editable = ("live",)
    readonly_fields = ("total_views", "total_clicks", "ad_report")
    search_fields = ("name", "flight__name", "flight__campaign__name", "text", "slug")

    # Exclude deprecated fields
    exclude = (
        "start_date",
        "sold_impressions",
        "sold_days",
        "sold_clicks",
        "cpc",
        "theme",
        "house",
        "community",
        "campaign",
    )

    def display_image(self, obj):
        if not obj.image:
            return ""

        return mark_safe(
            '<img src="{url}" style="width: 120px" />'.format(url=obj.image.url)
        )

    def num_clicks(self, obj):
        return obj.num_clicks or 0

    def num_views(self, obj):
        return obj.num_views or 0

    def ctr(self, obj):
        clicks = self.num_clicks(obj)
        views = self.num_views(obj)
        return "{:.3f}%".format(calculate_ctr(clicks, views))

    def ecpm(self, obj):
        if not obj.flight:
            return None

        clicks = self.num_clicks(obj)
        views = self.num_views(obj)

        cost = (clicks * obj.flight.cpc) + (views * obj.flight.cpm / 1000)
        return "${:.2f}".format(calculate_ecpm(cost, views))

    def ad_report(self, instance):
        if not instance.slug:
            return ""

        return mark_safe(
            '<a href="{url}">{name}</a>'.format(
                name=escape(instance.name) + " Report", url=instance.get_absolute_url()
            )
        )

    def get_queryset(self, request):
        queryset = super(AdvertisementAdmin, self).get_queryset(request)
        queryset = queryset.annotate(
            num_clicks=models.Sum("impressions__clicks"),
            num_views=models.Sum("impressions__views"),
        )
        return queryset


class CPCCPMFilter(admin.SimpleListFilter):
    title = "Paid Ad Type"
    parameter_name = "paid_ad_type"
    CPC = "CPC"
    CPM = "CPM"

    def lookups(self, request, model_admin):
        return ((self.CPC, self.CPC), (self.CPM, self.CPM))

    def queryset(self, request, queryset):
        value = self.value()
        if value == self.CPC:
            return queryset.filter(cpc__gt=0)
        if value == self.CPM:
            return queryset.filter(cpm__gt=0)
        return queryset


class FlightAdmin(RemoveDeleteMixin, admin.ModelAdmin):

    """Django admin admin configuration for ad Flights."""

    model = Flight
    form = FlightForm
    save_as = True

    list_display = (
        "name",
        "slug",
        "campaign",
        "live",
        "start_date",
        "end_date",
        "sold_clicks",
        "sold_impressions",
        "cpc",
        "cpm",
        "clicks_remaining",
        "views_remaining",
        "clicks_needed_today",  # Note: this requires an additional query per live CPC flight
        "views_needed_today",  # Note: this requires an additional query per live CPM flight
        "priority_multiplier",
        "num_clicks",
        "num_views",
        "num_ads",
        "ctr",
        "ecpm",
    )
    list_editable = ("live",)
    list_filter = ("live", "campaign__campaign_type", CPCCPMFilter, "campaign")
    list_select_related = ("campaign",)
    readonly_fields = (
        "related_ads",
        "total_clicks",
        "total_views",
        "clicks_today",
        "views_today",
        "clicks_needed_today",
        "views_needed_today",
        "weighted_clicks_needed_today",
    )
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug", "campaign__name", "campaign__slug")

    def num_clicks(self, obj):
        return obj.flight_total_clicks or 0

    def num_views(self, obj):
        return obj.num_views or 0

    def num_ads(self, obj):
        return obj.num_ads or 0

    def ctr(self, obj):
        clicks = self.num_clicks(obj)
        views = self.num_views(obj)
        return "{:.3f}%".format(calculate_ctr(clicks, views))

    def ecpm(self, obj):
        clicks = self.num_clicks(obj)
        views = self.num_views(obj)
        cost = (clicks * float(obj.cpc)) + (views * float(obj.cpm) / 1000.0)
        return "${:.2f}".format(calculate_ecpm(cost, views))

    def related_ads(self, obj):
        advertisements = list(obj.advertisements.all())
        return render_to_string(
            "adserver/admin/related_ads.html", {"ads": advertisements}
        )

    def get_queryset(self, request):
        queryset = super(FlightAdmin, self).get_queryset(request)

        # TODO: after we upgrade to Django 2.0, add `flight_clicks_today`
        # https://docs.djangoproject.com/en/2.0/topics/db/aggregation/#filtering-on-annotations
        queryset = queryset.annotate(
            flight_total_clicks=models.Sum("advertisements__impressions__clicks"),
            flight_total_views=models.Sum("advertisements__impressions__views"),
            num_views=models.Sum("advertisements__impressions__views"),
            num_ads=models.Count("advertisements", distinct=True),
        )
        return queryset


class CampaignAdmin(RemoveDeleteMixin, admin.ModelAdmin):

    """Django admin configuration for ad campaigns."""

    model = Campaign
    prepopulated_fields = {"slug": ("name",)}

    list_display = (
        "name",
        "advertiser",
        "campaign_type",
        "campaign_report",
        "max_sale_value",
        "total_value",
        "num_flights",
        "num_ads",
        "ctr",
        "ecpm",
    )
    list_filter = ("campaign_type", "advertiser")
    readonly_fields = ("campaign_report", "total_value", "related_flights")
    search_fields = ("name", "slug")

    def campaign_report(self, instance):
        if not instance.pk:
            return ""

        return mark_safe(
            '<a href="{url}">{name}</a>'.format(
                name=escape(instance.name) + " Report", url=instance.get_absolute_url()
            )
        )

    def num_ads(self, obj):
        return obj.num_ads or 0

    def num_flights(self, obj):
        return obj.num_flights or 0

    def num_clicks(self, obj):
        return obj.num_clicks or 0

    def num_views(self, obj):
        return obj.num_views or 0

    def total_value(self, obj):
        return "${:.2f}".format(obj.total_value())

    def ctr(self, obj):
        clicks = self.num_clicks(obj)
        views = self.num_views(obj)
        return "{:.3f}%".format(calculate_ctr(clicks, views))

    def ecpm(self, obj):
        views = self.num_views(obj)
        return "${:.2f}".format(calculate_ecpm(obj.total_value(), views))

    def related_flights(self, obj):
        flights = list(obj.flights.all())
        return render_to_string(
            "adserver/admin/related_flights.html", {"flights": flights}
        )

    def get_queryset(self, request):
        queryset = super(CampaignAdmin, self).get_queryset(request)
        queryset = queryset.annotate(
            campaign_total_value=models.Sum(
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
            ),
            num_flights=models.Count("flights", distinct=True),
            num_ads=models.Count("flights__advertisements", distinct=True),
            num_clicks=models.Sum("flights__advertisements__impressions__clicks"),
            num_views=models.Sum("flights__advertisements__impressions__views"),
        )
        return queryset


class AdImpressionsAdmin(RemoveDeleteMixin, admin.ModelAdmin):

    """Django admin configuration for the ad impressions."""

    readonly_fields = (
        "date",
        "advertisement",
        "publisher",
        "views",
        "clicks",
        "offers",
        "click_to_offer_rate",
        "view_to_offer_rate",
    )
    list_display = readonly_fields
    list_filter = ("advertisement__ad_type", "publisher")
    list_select_related = ["advertisement", "publisher"]
    search_fields = ["advertisement__slug", "advertisement__name"]

    def has_add_permission(self, request):
        """Clicks and views cannot be added through the admin."""
        return False

    def click_to_offer_rate(self, obj):
        return "{:.3f}%".format(calculate_ctr(obj.clicks, obj.offers))

    def view_to_offer_rate(self, obj):
        return "{:.3f}%".format(calculate_ctr(obj.views, obj.offers))


class AdBaseAdmin(RemoveDeleteMixin, admin.ModelAdmin):

    """Django admin configuration for the base class of ad views and clicks."""

    readonly_fields = (
        "date",
        "page_url",
        "country",
        "browser_family",
        "os_family",
        "is_bot",
        "is_mobile",
        "user_agent",
        "ip",
        "client_id",
    )
    list_display = readonly_fields[:-3]
    list_select_related = ("advertisement",)
    list_filter = ("is_mobile", "is_bot")
    exclude = ("advertisement", "url")
    search_fields = (
        "advertisement__name",
        "url",
        "ip",
        "country",
        "user_agent",
        "client_id",
    )

    def page_url(self, instance):
        return mark_safe('<a href="{url}">{url}</a>'.format(url=escape(instance.url)))

    def has_add_permission(self, request):
        """Clicks and views cannot be added through the admin."""
        return False


class ClickAdmin(AdBaseAdmin):

    """Django admin configuration for ad clicks."""

    model = Click

    # Browser Family and OS Family are not in the ``ViewAdmin.list_filter``
    # because they require a ``SELECT DISTINCT`` across the whole table
    list_filter = ("is_mobile", "is_bot", "browser_family", "os_family")


class ViewAdmin(AdBaseAdmin):

    """Django admin configuration for ad views."""

    model = View


admin.site.register(Publisher, PublisherAdmin)
admin.site.register(Advertiser, AdvertiserAdmin)
admin.site.register(View, ViewAdmin)
admin.site.register(Click, ClickAdmin)
admin.site.register(AdImpression, AdImpressionsAdmin)
admin.site.register(AdType, AdTypeAdmin)
admin.site.register(Advertisement, AdvertisementAdmin)
admin.site.register(Flight, FlightAdmin)
admin.site.register(Campaign, CampaignAdmin)
