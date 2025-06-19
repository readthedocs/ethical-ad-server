"""Django admin configuration for the ad server URL analyzer."""

from django.conf import settings
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import AnalyzedAdvertiserUrl
from .models import AnalyzedUrl


@admin.register(AnalyzedUrl)
class AnalyzedUrlAdmin(SimpleHistoryAdmin):
    """Django admin configuration for analyzed URLs."""

    list_display = (
        "url",
        "publisher",
        "keywords",
        "last_analyzed_date",
        "visits_since_last_analyzed",
    )
    list_per_page = 500
    list_filter = ("last_analyzed_date", "last_ad_served_date", "publisher")
    list_select_related = ("publisher",)
    raw_id_fields = ("publisher",)
    search_fields = ("url", "keywords")

    # Note: may need to use the estimated count paginator if this gets large


@admin.register(AnalyzedAdvertiserUrl)
class AnalyzedAdvertiserUrlAdmin(SimpleHistoryAdmin):
    """Django admin configuration for analyzed ads."""

    list_display = (
        "url",
        "advertiser",
        "keywords",
        "last_analyzed_date",
    )
    list_per_page = 500
    list_filter = ("last_analyzed_date", "advertiser")
    list_select_related = ("advertiser",)
    raw_id_fields = ("advertiser", "flights")
    search_fields = ("url", "keywords")

    # Note: may need to use the estimated count paginator if this gets large


if "ethicalads_ext.embedding" in settings.INSTALLED_APPS:
    from ethicalads_ext.embedding.models import AnalyzedAdvertiserUrlEmbedding
    from ethicalads_ext.embedding.models import AnalyzedUrlEmbedding
    from ethicalads_ext.embedding.tasks import analyze_advertiser_url
    from ethicalads_ext.embedding.tasks import analyze_publisher_url

    class AnalyzedUrlEmbeddingInline(admin.TabularInline):
        """Inline for AnalyzedUrlEmbedding."""

        model = AnalyzedUrlEmbedding
        readonly_fields = ["model"]
        fields = readonly_fields
        extra = 0

    @admin.action(description="Re-analyze the selected URLs")
    def reanalyze_publisher_url(self, request, queryset):
        for purl in queryset:
            analyze_publisher_url.apply_async(
                args=[purl.url, purl.publisher.slug],
                queue="analyzer",
            )

        self.message_user(request, "Re-analyzed selected URLs.")

    AnalyzedUrlAdmin.actions = [reanalyze_publisher_url]
    AnalyzedUrlAdmin.inlines = [AnalyzedUrlEmbeddingInline]

    class AnalyzedAdvertiserUrlEmbeddingInline(admin.TabularInline):
        """Inline for AnalyzedAdvertiserUrlEmbedding."""

        model = AnalyzedAdvertiserUrlEmbedding
        readonly_fields = ["model"]
        fields = readonly_fields
        extra = 0

    @admin.action(description="Re-analyze the selected URLs")
    def reanalyze_advertiser_url(self, request, queryset):
        """Re-analyze the selected URLs."""
        for aaurl in queryset:
            analyze_advertiser_url.apply_async(
                args=[aaurl.url, aaurl.advertiser.slug],
                queue="analyzer",
            )
        self.message_user(request, "Re-analyzed selected URLs.")

    AnalyzedAdvertiserUrlAdmin.actions = [reanalyze_advertiser_url]
    AnalyzedAdvertiserUrlAdmin.inlines = [AnalyzedAdvertiserUrlEmbeddingInline]
