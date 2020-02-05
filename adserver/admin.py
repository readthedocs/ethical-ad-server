"""Django admin configuration for the ad server."""
from django.contrib import admin
from django.db import models
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .forms import FlightAdminForm
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

    list_display = ("name", "report")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("modified", "created")

    def report(self, instance):
        if not instance.pk:
            return ""

        return mark_safe(
            '<a href="{url}">{name}</a>'.format(
                name=escape(instance.name) + " Report", url=instance.get_absolute_url()
            )
        )


class AdvertiserAdmin(RemoveDeleteMixin, admin.ModelAdmin):

    """Django admin configuration for advertisers."""

    list_display = ("name", "report")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("modified", "created")

    def report(self, instance):
        if not instance.pk:
            return ""

        return mark_safe(
            '<a href="{url}">{name}</a>'.format(
                name=escape(instance.name) + " Report", url=instance.get_absolute_url()
            )
        )


class AdTypeAdmin(admin.ModelAdmin):

    """Django admin configuration for ad types."""

    model = AdType
    save_as = True
    prepopulated_fields = {"slug": ("name",)}
    list_display = ("name", "publisher")
    list_select_related = ("publisher",)
    readonly_fields = ("modified", "created")
    search_fields = ("name", "slug", "publisher__name", "publisher__slug")


class AdvertisementMixin:

    """Used by the AdvertisementInline and the AdvertisementAdmin."""

    MAX_IMAGE_WIDTH = 120

    def ad_image(self, obj):
        if not obj.image:
            return ""

        return mark_safe(
            f'<img src="{obj.image.url}" style="max-width: {self.MAX_IMAGE_WIDTH}px" />'
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

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if self.list_select_related is True:
            queryset = queryset.select_related()
        elif self.list_select_related:
            queryset = queryset.select_related(*self.list_select_related)
        queryset = queryset.annotate(
            num_clicks=models.Sum("impressions__clicks"),
            num_views=models.Sum("impressions__views"),
        )
        return queryset


class AdvertisementAdmin(RemoveDeleteMixin, AdvertisementMixin, admin.ModelAdmin):

    """Django admin configuration for advertisements."""

    model = Advertisement
    save_as = True
    prepopulated_fields = {"slug": ("name",)}
    list_display = (
        "ad_image",
        "name",
        "slug",
        "flight",
        "ad_type",
        "live",
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
    readonly_fields = ("total_views", "total_clicks", "modified", "created")
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


class AdvertisementsInline(AdvertisementMixin, admin.TabularInline):

    """An inline for displaying non-editable list of advertisements."""

    model = Advertisement

    can_delete = False
    fields = (
        "ad_image",
        "name",
        "ad_type",
        "live",
        "num_views",
        "num_clicks",
        "ctr",
        "ecpm",
    )
    list_select_related = ("flight", "ad_type")
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request):
        return False


class FlightMixin:

    """Used by the FlightAdmin and FlightInline."""

    def num_ads(self, obj):
        return obj.num_ads or 0

    def value_remaining(self, obj):
        return "${:.2f}".format(obj.value_remaining())

    def total_value(self, obj):
        total = 0.0
        total += float(obj.cpm * obj.total_views) / 1000.0
        total += float(obj.cpc * obj.total_clicks)
        return "${:.2f}".format(total)

    def ctr(self, obj):
        clicks = obj.total_clicks
        views = obj.total_views
        return "{:.3f}%".format(calculate_ctr(clicks, views))

    def ecpm(self, obj):
        clicks = obj.total_clicks
        views = obj.total_views
        cost = (clicks * float(obj.cpc)) + (views * float(obj.cpm) / 1000.0)
        return "${:.2f}".format(calculate_ecpm(cost, views))


class FlightAdmin(RemoveDeleteMixin, FlightMixin, admin.ModelAdmin):

    """Django admin admin configuration for ad Flights."""

    model = Flight
    form = FlightAdminForm
    save_as = True

    inlines = (AdvertisementsInline,)
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
        "value_remaining",
        "clicks_needed_today",
        "views_needed_today",
        "priority_multiplier",
        "total_clicks",
        "total_views",
        "num_ads",
        "ctr",
        "ecpm",
    )
    list_editable = ("live",)
    list_filter = ("live", "campaign__campaign_type", CPCCPMFilter, "campaign")
    list_select_related = ("campaign",)
    readonly_fields = (
        "value_remaining",
        "total_value",
        "total_clicks",
        "total_views",
        "clicks_today",
        "views_today",
        "clicks_needed_today",
        "views_needed_today",
        "weighted_clicks_needed_today",
        "modified",
        "created",
    )
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug", "campaign__name", "campaign__slug")

    def get_queryset(self, request):
        queryset = super(FlightAdmin, self).get_queryset(request)
        queryset = queryset.annotate(
            num_ads=models.Count("advertisements", distinct=True)
        )
        return queryset


class FlightsInline(FlightMixin, admin.TabularInline):

    """An inline for displaying non-editable list of flights."""

    model = Flight

    can_delete = False
    fields = (
        "name",
        "live",
        "start_date",
        "end_date",
        "sold_clicks",
        "sold_impressions",
        "cpc",
        "cpm",
        "clicks_remaining",
        "views_remaining",
        "total_clicks",
        "total_views",
        "ctr",
        "ecpm",
    )
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request):
        return False


class CampaignAdmin(RemoveDeleteMixin, admin.ModelAdmin):

    """Django admin configuration for ad campaigns."""

    model = Campaign
    prepopulated_fields = {"slug": ("name",)}

    inlines = (FlightsInline,)
    list_display = (
        "name",
        "advertiser",
        "campaign_type",
        "campaign_report",
        "total_value",
        "num_flights",
        "num_ads",
        "total_views",
        "total_clicks",
        "ctr",
        "ecpm",
    )
    list_filter = ("campaign_type", "advertiser")
    list_select_related = ("advertiser",)
    readonly_fields = ("campaign_report", "total_value", "modified", "created")
    search_fields = ("name", "slug")

    def campaign_report(self, instance):
        if not instance.pk or not instance.advertiser:
            return ""

        return mark_safe(
            '<a href="{url}">{name}</a>'.format(
                name=escape(instance.name) + " Report",
                url=instance.advertiser.get_absolute_url(),
            )
        )

    def num_ads(self, obj):
        return obj.num_ads or 0

    def num_flights(self, obj):
        return obj.num_flights or 0

    def total_clicks(self, obj):
        return obj.total_clicks or 0

    def total_views(self, obj):
        return obj.total_views or 0

    def total_value(self, obj):
        return "${:.2f}".format(obj.total_value())

    def ctr(self, obj):
        clicks = self.total_clicks(obj)
        views = self.total_views(obj)
        return "{:.3f}%".format(calculate_ctr(clicks, views))

    def ecpm(self, obj):
        views = self.total_views(obj)
        return "${:.2f}".format(calculate_ecpm(obj.total_value(), views))

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
            total_clicks=models.Sum("flights__advertisements__impressions__clicks"),
            total_views=models.Sum("flights__advertisements__impressions__views"),
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
    readonly_fields = ("modified", "created")
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
        "advertisement",
        "publisher",
        "page_url",
        "country",
        "browser_family",
        "os_family",
        "is_mobile",
        "is_bot",
        "user_agent",
        "ip",
        "client_id",
        "modified",
        "created",
    )
    list_display = readonly_fields[:-3]
    list_select_related = ("advertisement", "publisher")
    list_filter = ("is_mobile",)
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
