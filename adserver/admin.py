"""Django admin configuration for the ad server."""

from datetime import timedelta

import stripe
from django.conf import settings
from django.contrib import admin
from django.contrib import messages
from django.db import models
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from djstripe.models import Invoice
from simple_history.admin import SimpleHistoryAdmin

from .forms import AdvertisementAdminForm
from .forms import FlightAdminForm
from .mixins import EstimatedCountPaginator
from .models import AdImpression
from .models import AdType
from .models import Advertisement
from .models import Advertiser
from .models import AdvertiserImpression
from .models import Campaign
from .models import Click
from .models import CountryRegion
from .models import Flight
from .models import GeoImpression
from .models import Keyword
from .models import KeywordImpression
from .models import Offer
from .models import PlacementImpression
from .models import Publisher
from .models import PublisherGroup
from .models import PublisherImpression
from .models import PublisherPaidImpression
from .models import PublisherPayout
from .models import Region
from .models import RegionImpression
from .models import RegionTopicImpression
from .models import Topic
from .models import UpliftImpression
from .models import View
from .utils import calculate_ctr
from .utils import calculate_ecpm


class RemoveDeleteMixin:
    """Removes the ability to delete this model from the admin."""

    def get_actions(self, request):
        actions = super().get_actions(request)
        if "delete_selected" in actions:
            del actions["delete_selected"]  # pragma: no cover
        return actions

    def has_delete_permission(self, request, obj=None):  # pylint: disable=unused-argument
        return False


class KeywordInline(admin.TabularInline):
    """For inlining the keywords on the topic admin."""

    model = Keyword.topics.through

    can_delete = False
    extra = 0
    fields = ("keyword",)
    list_select_related = ("keyword",)
    readonly_fields = fields
    show_change_link = True


@admin.register(Keyword)
class KeywordAdmin(admin.ModelAdmin):
    list_display = ("slug",)
    list_filter = ("topics",)
    list_per_page = 500
    ordering = ("slug",)
    search_fields = ("slug",)


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    inlines = (KeywordInline,)
    list_display = (
        "name",
        "slug",
        "selectable",
    )
    list_filter = ("selectable",)
    list_per_page = 1000
    ordering = ("slug",)
    search_fields = ("name", "slug")


@admin.register(CountryRegion)
class CountryRegionAdmin(admin.ModelAdmin):
    list_display = (
        "country",
        "region",
    )
    list_filter = ("region",)
    list_per_page = 500
    ordering = ("country", "region__order")
    search_fields = ("country", "region__slug")


class CountryInline(admin.TabularInline):
    """For inlining the countries on the region admin."""

    model = CountryRegion

    can_delete = False
    extra = 0
    fields = (
        "country",
        "country_code",
    )
    list_select_related = ("region",)
    readonly_fields = fields
    show_change_link = True

    def country_code(self, obj):
        return obj.country.code


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    inlines = (CountryInline,)
    list_display = (
        "name",
        "slug",
        "order",
        "selectable",
    )
    list_filter = ("selectable",)
    list_per_page = 1000
    ordering = ("order", "slug")
    search_fields = ("name", "slug")


@admin.register(Publisher)
class PublisherAdmin(RemoveDeleteMixin, SimpleHistoryAdmin):
    """Django admin configuration for publishers."""

    list_display = (
        "name",
        "slug",
        "report",
        "revenue_share_percentage",
        "payout_method",
        "unauthed_ad_decisions",
        "allow_paid_campaigns",
        "allow_affiliate_campaigns",
        "allow_community_campaigns",
        "allow_house_campaigns",
        "record_views",
    )
    list_filter = (
        "payout_method",
        "unauthed_ad_decisions",
        "allow_paid_campaigns",
        "allow_affiliate_campaigns",
        "allow_community_campaigns",
        "allow_house_campaigns",
        "record_views",
    )
    list_per_page = 500
    prepopulated_fields = {"slug": ("name",)}
    raw_id_fields = ("djstripe_account",)
    readonly_fields = ("publisher_group_list", "modified", "created")
    search_fields = ("name", "slug")

    def publisher_group_list(self, instance):
        if not instance.pk:
            return ""  # pragma: no cover

        return ", ".join([pg.name for pg in instance.publisher_groups.all()])

    def report(self, instance):
        if not instance.pk:
            return ""  # pragma: no cover

        return format_html(
            '<a href="{}">{}</a>',
            instance.get_absolute_url(),
            f"{instance.name} Report",
        )


class CampaignInline(admin.TabularInline):
    """For inlining the campaigns on the advertiser admin."""

    model = Campaign

    can_delete = False
    fields = (
        "id",
        "name",
        "campaign_type",
    )
    readonly_fields = (
        "name",
        "campaign_type",
    )
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Advertiser)
class AdvertiserAdmin(RemoveDeleteMixin, SimpleHistoryAdmin):
    """Django admin configuration for advertisers."""

    actions = ["action_create_draft_invoice"]
    inlines = (CampaignInline,)
    list_display = ("name", "report", "stripe_customer")
    list_per_page = 500
    prepopulated_fields = {"slug": ("name",)}
    raw_id_fields = ("djstripe_customer",)
    readonly_fields = ("modified", "created")
    search_fields = ("name", "slug", "djstripe_customer__id")

    @admin.action(description=_("Create a draft invoice for this customer"))
    def action_create_draft_invoice(self, request, queryset):
        """Create a draft invoice for this customer with metadata attached."""
        if not settings.STRIPE_ENABLED:
            messages.add_message(
                request,
                messages.ERROR,
                _("Stripe is not configured. Please set the envvar STRIPE_SECRET_KEY."),
            )
            return

        flight_start = timezone.now()
        flight_end = flight_start + timedelta(days=30)

        for advertiser in queryset:
            if advertiser.djstripe_customer:
                # Amounts, prices, and description can be customized before sending
                stripe.InvoiceItem.create(
                    customer=advertiser.djstripe_customer.id,
                    description="Advertising - per 1k impressions",
                    quantity=200,
                    unit_amount=300,  # in US cents
                    currency="USD",
                )

                # https://stripe.com/docs/api/invoices/create
                inv = stripe.Invoice.create(
                    customer=advertiser.djstripe_customer.id,
                    auto_advance=False,  # Draft invoice
                    collection_method="send_invoice",
                    custom_fields=[
                        {"name": "Advertiser", "value": advertiser.slug[:30]},
                        {
                            "name": "Estimated Start",
                            "value": flight_start.strftime("%Y-%m-%d"),
                        },
                        {
                            "name": "Estimated End",
                            "value": flight_end.strftime("%Y-%m-%d"),
                        },
                    ],
                    days_until_due=30,
                )
                invoice = Invoice.sync_from_stripe_data(inv)

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    _(
                        "New Stripe invoice for {}: {}".format(
                            advertiser, invoice.get_stripe_dashboard_url()
                        )
                    ),
                )
            else:
                messages.add_message(
                    request,
                    messages.ERROR,
                    _("No Stripe customer ID for {}".format(advertiser)),
                )

    def report(self, instance):
        if not instance.pk:
            return ""  # pragma: no cover

        return format_html(
            '<a href="{}">{}</a>',
            instance.get_absolute_url(),
            f"{instance.name} Report",
        )

    def stripe_customer(self, obj):
        if obj.djstripe_customer:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>',
                obj.djstripe_customer.get_stripe_dashboard_url(),
                obj.djstripe_customer.name,
            )
        return None


@admin.register(AdType)
class AdTypeAdmin(SimpleHistoryAdmin):
    """Django admin configuration for ad types."""

    model = AdType
    save_as = True
    prepopulated_fields = {"slug": ("name",)}
    list_display = (
        "name",
        "max_text_length",
        "order",
        "default_enabled",
        "has_image",
        "has_text",
        "deprecated",
    )
    list_filter = ("has_image", "has_text", "default_enabled", "deprecated")
    readonly_fields = ("modified", "created")
    search_fields = ("name", "slug")


class AdvertisementMixin:
    """Used by the AdvertisementInline and the AdvertisementAdmin."""

    MAX_IMAGE_WIDTH = 120

    def ad_image(self, obj):
        if not obj.image:
            return ""

        return format_html(
            '<img src="{}" style="max-width: {}px" />',
            obj.image.url,
            self.MAX_IMAGE_WIDTH,
        )

    def ctr(self, obj):
        return "{:.3f}%".format(obj.ctr())

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if self.list_select_related is True:
            queryset = queryset.select_related()  # pragma: no cover
        elif self.list_select_related:
            queryset = queryset.select_related(
                *self.list_select_related
            )  # pragma: no cover

        return queryset


@admin.register(Advertisement)
class AdvertisementAdmin(RemoveDeleteMixin, AdvertisementMixin, SimpleHistoryAdmin):
    """Django admin configuration for advertisements."""

    form = AdvertisementAdminForm
    model = Advertisement
    save_as = True
    list_per_page = 50  # make page load a bit faster
    prepopulated_fields = {"slug": ("name",)}
    list_display = (
        "ad_image",
        "name",
        "slug",
        "flight",
        "live",
    )
    list_display_links = ("name",)
    list_select_related = ("flight", "flight__campaign__advertiser")
    list_filter = (
        "live",
        "flight__campaign__campaign_type",
        "ad_types",
        "flight__campaign__advertiser",
    )
    list_editable = ("live",)
    raw_id_fields = ("flight",)
    readonly_fields = (
        "ad_image",
        "total_views",
        "total_clicks",
        "modified",
        "created",
        "ctr",
    )
    search_fields = (
        "name",
        "flight__name",
        "flight__campaign__name",
        "flight__campaign__advertiser__name",
        "text",
        "slug",
    )
    ordering = ("-created",)


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
            return queryset.filter(cpc__gt=0)  # pragma: no cover
        if value == self.CPM:
            return queryset.filter(cpm__gt=0)  # pragma: no cover
        return queryset


class AdvertisementsInline(AdvertisementMixin, admin.TabularInline):
    """An inline for displaying non-editable list of advertisements."""

    model = Advertisement

    can_delete = False
    fields = (
        "ad_image",
        "name",
        "ad_types",
        "live",
        "num_views",
        "num_clicks",
        "ctr",
        "ecpm",
    )
    list_select_related = ("flight",)
    readonly_fields = fields
    show_change_link = True

    def num_clicks(self, obj):
        return obj.num_clicks or 0

    def num_views(self, obj):
        return obj.num_views or 0

    def ctr(self, obj):
        return "{:.3f}%".format(obj.ctr())

    def ecpm(self, obj):
        if not obj.flight:
            return None  # pragma: no cover

        clicks = self.num_clicks(obj)
        views = self.num_views(obj)

        cost = (clicks * obj.flight.cpc) + (views * obj.flight.cpm / 1000)
        return "${:.2f}".format(calculate_ecpm(cost, views))

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(
            num_clicks=models.Sum("impressions__clicks"),
            num_views=models.Sum("impressions__views"),
        )
        return queryset.prefetch_related("ad_types")

    def has_add_permission(self, request, obj=None):
        return False


class InvoiceInline(admin.TabularInline):
    """List of Stripe invoices for a flight."""

    model = Flight.invoices.through
    can_delete = True
    extra = 1
    fields = (
        "invoice",
        "total",
        "due_date",
        "status",
    )
    list_select_related = ("invoice", "flight")
    raw_id_fields = ("invoice",)
    readonly_fields = (
        "total",
        "due_date",
        "status",
    )

    def total(self, obj):
        return obj.invoice.total

    def due_date(self, obj):
        return obj.invoice.due_date

    def status(self, obj):
        return obj.invoice.status


class FlightMixin:
    """Used by the FlightAdmin and FlightInline."""

    def num_ads(self, obj):
        return obj.num_ads or 0

    def value_remaining(self, obj):
        return "${:.2f}".format(obj.value_remaining())

    def projected_total_value(self, obj):
        return "${:.2f}".format(obj.projected_total_value())

    def ctr(self, obj):
        return "{:.3f}%".format(obj.ctr())

    def ecpm(self, obj):
        clicks = obj.total_clicks
        views = obj.total_views
        cost = (clicks * float(obj.cpc)) + (views * float(obj.cpm) / 1000.0)
        return "${:.2f}".format(calculate_ecpm(cost, views))


@admin.register(Flight)
class FlightAdmin(RemoveDeleteMixin, FlightMixin, SimpleHistoryAdmin):
    """Django admin admin configuration for ad Flights."""

    model = Flight
    form = FlightAdminForm
    save_as = True

    actions = ["action_create_draft_invoice"]
    inlines = (AdvertisementsInline, InvoiceInline)
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
        "clicks_needed_this_interval",
        "views_needed_this_interval",
        "priority_multiplier",
        "total_clicks",
        "total_views",
        "num_ads",
        "ctr",
        "ecpm",
    )
    list_editable = ("live",)
    list_filter = (
        "live",
        "campaign__campaign_type",
        CPCCPMFilter,
        "campaign__advertiser",
    )
    list_select_related = ("campaign", "campaign__advertiser")
    raw_id_fields = ("campaign", "invoices")
    readonly_fields = (
        "value_remaining",
        "projected_total_value",
        "total_clicks",
        "total_views",
        "clicks_today",
        "views_today",
        "clicks_needed_this_interval",
        "views_needed_this_interval",
        "weighted_clicks_needed_this_interval",
        "modified",
        "created",
    )
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug", "campaign__name", "campaign__slug")

    @admin.action(description=_("Create a draft invoice for selected flights"))
    def action_create_draft_invoice(self, request, queryset):
        """
        Create a draft invoice for selected flights with metadata attached.

        This fails with a message if the flights aren't all from the same advertiser.
        """
        if not settings.STRIPE_ENABLED:
            messages.add_message(
                request,
                messages.ERROR,
                _("Stripe is not configured. Please set the envvar STRIPE_SECRET_KEY."),
            )
            return

        flights = list(queryset.select_related("campaign", "campaign__advertiser"))

        if not flights:
            # Django actually doesn't take this path and instead shows its own error message
            return  # pragma: no cover
        if len({f.campaign.advertiser_id for f in flights}) > 1:
            messages.add_message(
                request,
                messages.ERROR,
                _("All selected flights must be from a single advertiser."),
            )
            return

        earliest_start_date = min([f.start_date for f in flights])
        latest_end_date = max([f.end_date for f in flights])
        advertiser = [f.campaign.advertiser for f in flights][0]

        if not advertiser.djstripe_customer:
            messages.add_message(
                request,
                messages.ERROR,
                _("No Stripe customer ID for {}".format(advertiser)),
            )
            return

        # Any flight with the discount will result in the discount being in the memo
        invoice_discount = None
        total_cost = 0  # In US cents

        for flight in flights:
            message_components = ["Advertising", flight.name]
            unit_amount = 0
            quantity = 1

            if flight.cpc:
                message_components.append("per click")
                unit_amount = flight.cpc * 100  # Convert to US cents
                quantity = flight.sold_clicks
            elif flight.cpm:
                # Convert CPM to US cents (eg. $4.25 CPM -> 0.425 cents)
                unit_amount = flight.cpm / 10
                message_components.append("${:.2f} CPM".format(flight.cpm))
                quantity = flight.sold_impressions

            if flight.discount:
                invoice_discount = flight.discount

            total_cost += unit_amount * quantity

            # Amounts, prices, and description can be customized before sending
            stripe.InvoiceItem.create(
                customer=advertiser.djstripe_customer.id,
                description=" - ".join(message_components),
                quantity=quantity,
                unit_amount_decimal=unit_amount,  # in US cents
                currency="USD",
                metadata={
                    "Advertiser": advertiser.slug[:30],
                    "Flight": flight.slug[:30],
                    "Flight Start": flight.start_date.strftime("%Y-%m-%d"),
                    "Flight End": flight.end_date.strftime("%Y-%m-%d"),
                },
            )

        # https://stripe.com/docs/api/invoices/create
        description = "Thanks for your business!"
        if invoice_discount:
            description = f"Includes {invoice_discount} discount. " + description
        inv = stripe.Invoice.create(
            customer=advertiser.djstripe_customer.id,
            auto_advance=False,  # Draft invoice
            collection_method="send_invoice",
            description=description,
            custom_fields=[
                {"name": "Advertiser", "value": advertiser.slug[:30]},
                {
                    "name": "Estimated Start",
                    "value": earliest_start_date.strftime("%Y-%m-%d"),
                },
                {
                    "name": "Estimated End",
                    "value": latest_end_date.strftime("%Y-%m-%d"),
                },
            ],
            days_until_due=30,
        )
        invoice = Invoice.sync_from_stripe_data(inv)

        # Attach Stripe invoices to flights
        # There isn't a good way to mock invoices for tests so this check is to mock the invoice
        if invoice.pk:
            for flight in flights:
                flight.invoices.add(invoice)

        messages.add_message(
            request,
            messages.SUCCESS,
            _(
                "New Stripe invoice for {}: {}".format(
                    advertiser, invoice.get_stripe_dashboard_url()
                )
            ),
        )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
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
        "value_remaining",
        "total_clicks",
        "total_views",
        "ctr",
        "ecpm",
    )
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False  # pragma: no cover


@admin.register(Campaign)
class CampaignAdmin(RemoveDeleteMixin, SimpleHistoryAdmin):
    """Django admin configuration for ad campaigns."""

    model = Campaign
    prepopulated_fields = {"slug": ("name",)}

    inlines = (FlightsInline,)
    list_display = (
        "name",
        "advertiser",
        "campaign_type",
        "campaign_report",
        "num_flights",
        "num_ads",
    )
    list_filter = ("campaign_type", "advertiser")
    list_per_page = 500
    list_select_related = ("advertiser",)
    raw_id_fields = ("advertiser",)
    readonly_fields = ("campaign_report", "modified", "created")
    search_fields = ("name", "slug")

    def campaign_report(self, instance):
        if not instance.pk or not instance.advertiser:
            return ""  # pragma: no cover

        return format_html(
            '<a href="{}">{}</a>',
            instance.advertiser.get_absolute_url(),
            f"{instance.name} Report",
        )

    def num_ads(self, obj):
        return obj.num_ads or 0

    def num_flights(self, obj):
        return obj.num_flights or 0

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(
            num_flights=models.Count("flights", distinct=True),
            num_ads=models.Count("flights__advertisements", distinct=True),
        )
        return queryset


class ImpressionsAdmin(RemoveDeleteMixin, admin.ModelAdmin):
    """Django admin configuration for the ad impressions."""

    readonly_fields = (
        "date",
        "advertisement",
        "publisher",
        "views",
        "clicks",
        "offers",
        "decisions",
        "click_to_offer_rate",
        "view_to_offer_rate",
        "modified",
        "created",
    )
    list_display = readonly_fields
    list_filter = (
        "advertisement__ad_types",
        "publisher",
        "advertisement__flight__campaign__advertiser",
    )
    list_select_related = ("advertisement", "publisher")
    search_fields = ("advertisement__slug", "advertisement__name")

    def has_add_permission(self, request):
        """Clicks and views cannot be added through the admin."""
        return False

    def click_to_offer_rate(self, obj):
        return "{:.3f}%".format(calculate_ctr(obj.clicks, obj.offers))

    def view_to_offer_rate(self, obj):
        return "{:.3f}%".format(calculate_ctr(obj.views, obj.offers))


class AdImpressionAdmin(ImpressionsAdmin):
    readonly_fields = ("view_time",) + ImpressionsAdmin.readonly_fields


@admin.register(AdvertiserImpression)
class AdvertiserImpressionAdmin(ImpressionsAdmin):
    date_hierarchy = "date"
    readonly_fields = (
        "date",
        "advertiser",
        "views",
        "clicks",
        "offers",
        "decisions",
        "click_to_offer_rate",
        "view_to_offer_rate",
        "spend",
        "modified",
        "created",
    )
    list_display = readonly_fields
    list_filter = ("advertiser",)
    list_select_related = ("advertiser",)
    search_fields = ("advertiser__name",)


@admin.register(PublisherImpression, PublisherPaidImpression)
class PublisherImpressionAdmin(ImpressionsAdmin):
    date_hierarchy = "date"
    readonly_fields = (
        "date",
        "publisher",
        "views",
        "clicks",
        "offers",
        "decisions",
        "click_to_offer_rate",
        "view_to_offer_rate",
        "revenue",
        "modified",
        "created",
    )
    list_display = readonly_fields
    list_filter = ("publisher",)
    list_select_related = ("publisher",)
    search_fields = ("publisher__name",)


class UpliftImpressionAdmin(ImpressionsAdmin):
    pass


class PlacementImpressionAdmin(ImpressionsAdmin):
    readonly_fields = ("div_id", "ad_type_slug") + ImpressionsAdmin.readonly_fields
    list_display = ("div_id", "ad_type_slug") + ImpressionsAdmin.list_display
    search_fields = ("div_id", "ad_type_slug") + ImpressionsAdmin.search_fields


class GeoImpressionAdmin(ImpressionsAdmin):
    readonly_fields = ("country",) + ImpressionsAdmin.readonly_fields
    list_display = ("country",) + ImpressionsAdmin.list_display
    search_fields = ("country",) + ImpressionsAdmin.search_fields


class KeywordImpressionAdmin(ImpressionsAdmin):
    readonly_fields = ("keyword",) + ImpressionsAdmin.readonly_fields
    list_display = ("keyword",) + ImpressionsAdmin.list_display
    search_fields = ("keyword",) + ImpressionsAdmin.search_fields


class AdBaseAdmin(RemoveDeleteMixin, admin.ModelAdmin):
    """Django admin configuration for the base class of ad views and clicks."""

    readonly_fields = (
        "date",
        "advertisement",
        "publisher",
        "page_url",
        "keywords",
        "country",
        "browser_family",
        "os_family",
        "is_mobile",
        "is_proxy",
        "paid_eligible",
        "user_agent",
        "ip",
        "div_id",
        "ad_type_slug",
        "client_id",
        "modified",
        "created",
    )
    list_display = readonly_fields[:-3]
    list_select_related = ("advertisement", "publisher")
    list_filter = (
        "is_mobile",
        "is_proxy",
        "paid_eligible",
        "publisher",
        "advertisement__flight__campaign__advertiser",
    )
    paginator = EstimatedCountPaginator
    search_fields = (
        "advertisement__name",
        "url",
        "ip",
        "country",
        "user_agent",
        "client_id",
    )
    show_full_result_count = False

    def page_url(self, instance):
        if instance.url:
            return format_html(
                '<a href="{}">{}</a>',
                instance.url,
                instance.url,
            )
        return None

    def has_add_permission(self, request):
        """Clicks and views cannot be added through the admin."""
        return False


@admin.register(Offer)
class OfferAdmin(AdBaseAdmin):
    """Django admin configuration for ad offers."""

    model = Offer
    actions = ["refund_impressions"]
    readonly_fields = AdBaseAdmin.readonly_fields + (
        "view_time",
        "viewed",
        "clicked",
        "is_refunded",
    )
    list_display = AdBaseAdmin.list_display + ("viewed", "clicked", "is_refunded")
    list_filter = AdBaseAdmin.list_filter + ("is_refunded",)

    # Without this, the django admin will order by date and PK
    # resulting in a very expensive query
    # This is due to how the admin determines that the order should be deterministic.
    # https://docs.djangoproject.com/en/4.2/ref/contrib/admin/#django.contrib.admin.ModelAdmin.ordering
    # Ordering by a UUID isn't very useful.
    ordering = ("-pk",)

    def refund_impressions(self, request, queryset):
        """Process a refund for the selected impressions."""
        if not request.POST.get("confirm"):
            response = TemplateResponse(
                request,
                "admin/confirm_refund.html",
                {
                    "queryset": queryset,
                    "action": "refund_impressions",
                    "model": self.model,
                    "opts": self.model._meta,
                    "title": _("Refund impressions"),
                },
            )
            return response

        queryset = queryset.select_related(
            "publisher", "advertisement", "advertisement__flight"
        )

        count = 0
        for impression in queryset:
            if impression.refund():
                count += 1

        messages.add_message(
            request,
            messages.SUCCESS,
            _(
                "%(cnt)s %(type)s refunded"
                % {"cnt": count, "type": self.model._meta.verbose_name_plural}
            ),
        )

        return None


@admin.register(Click)
class ClickAdmin(AdBaseAdmin):
    """Django admin configuration for ad clicks."""

    model = Click


@admin.register(View)
class ViewAdmin(AdBaseAdmin):
    """Django admin configuration for ad views."""

    model = View


@admin.register(PublisherPayout)
class PublisherPayoutAdmin(SimpleHistoryAdmin):
    list_display = (
        "pk",
        "amount",
        "status",
        "publisher",
        "date",
        "method",
        "modified",
        "created",
    )
    list_filter = ("method", "publisher", "status")
    list_select_related = ("publisher",)
    model = PublisherPayout
    readonly_fields = ("modified", "created")
    search_fields = ("publisher__name", "pk")


@admin.register(PublisherGroup)
class PublisherGroupAdmin(SimpleHistoryAdmin):
    list_display = ("name", "slug", "default_enabled", "modified", "created")
    list_filter = (
        "default_enabled",
        "publishers",
    )
    model = PublisherGroup
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("modified", "created")


class RegionImpressionAdmin(admin.ModelAdmin):
    readonly_fields = (
        "__str__",
        "date",
        "views",
        "clicks",
        "offers",
        "decisions",
        "modified",
        "created",
    )
    list_display = readonly_fields


class RegionTopicAdmin(admin.ModelAdmin):
    readonly_fields = (
        "__str__",
        "date",
        "views",
        "clicks",
        "offers",
        "decisions",
        "modified",
        "created",
    )
    list_display = readonly_fields


# Don't register Impression Admin's outside dev, since they will just 502 from too much data.
if settings.DEBUG:
    admin.site.register(AdImpression, AdImpressionAdmin)
    admin.site.register(UpliftImpression, UpliftImpressionAdmin)
    admin.site.register(GeoImpression, GeoImpressionAdmin)
    admin.site.register(PlacementImpression, PlacementImpressionAdmin)
    admin.site.register(KeywordImpression, KeywordImpressionAdmin)
    admin.site.register(RegionTopicImpression, RegionTopicAdmin)
    admin.site.register(RegionImpression, RegionImpressionAdmin)
