"""Export ad server decision data to SQL commands for Cloudflare D1 / Wrangler local testing."""

import hashlib
import html
import logging
from io import StringIO

import bleach
from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import models

from ...models import AdType
from ...models import Campaign
from ...models import Flight
from ...models import Publisher
from ...utils import get_ad_day
from ...utils import get_domain_from_url


log = logging.getLogger(__name__)


def sql_quote(val):
    """Format a value as a SQL literal string, number, boolean, or NULL."""
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val).replace("'", "''")
    return f"'{s}'"


class Command(BaseCommand):
    """Management command to export decision engine data to D1 SQL format."""

    help = "Export active ad server decision data as SQL statements for Cloudflare D1"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            "-o",
            type=str,
            help="Path to file to write SQL output (defaults to stdout if omitted)",
        )

    def handle(self, *args, **options):
        output_file = options.get("output")
        buffer = StringIO()

        buffer.write("-- Exported SQL data for Cloudflare D1 decision worker\n\n")

        # 1. Export Publishers (non-disabled)
        publishers = Publisher.objects.filter(disabled=False).order_by("slug")
        buffer.write(f"-- Publishers ({publishers.count()})\n")
        for pub in publishers:
            kw_list = pub.keywords
            default_keywords_str = "|".join(kw_list) if kw_list else ""
            sql = (
                "INSERT OR REPLACE INTO publishers ("
                "slug, name, disabled, allow_paid_campaigns, allow_house_campaigns, "
                "allow_community_campaigns, allow_affiliate_campaigns, allow_api_keywords, default_keywords"
                ") VALUES ("
                f"{sql_quote(pub.slug)}, {sql_quote(pub.name)}, {sql_quote(pub.disabled)}, "
                f"{sql_quote(pub.allow_paid_campaigns)}, {sql_quote(pub.allow_house_campaigns)}, "
                f"{sql_quote(pub.allow_community_campaigns)}, {sql_quote(pub.allow_affiliate_campaigns)}, "
                f"{sql_quote(pub.allow_api_keywords)}, {sql_quote(default_keywords_str)}"
                ");\n"
            )
            buffer.write(sql)

        buffer.write("\n")

        # 2. Query Active Flights (live=True, start_date <= today, and has >=1 live ad)
        today = get_ad_day().date()
        active_flights = (
            Flight.objects.filter(live=True, start_date__lte=today)
            .annotate(
                num_live_ads=models.Count(
                    "advertisements",
                    filter=models.Q(advertisements__live=True),
                )
            )
            .filter(num_live_ads__gt=0)
            .select_related("campaign", "campaign__advertiser")
            .prefetch_related("advertisements", "advertisements__ad_types")
            .order_by("slug")
        )

        live_ads_list = []
        ad_type_pks = set()

        for flight in active_flights:
            flight_live_ads = [ad for ad in flight.advertisements.all() if ad.live]
            live_ads_list.extend(flight_live_ads)
            for ad in flight_live_ads:
                for at in ad.ad_types.all():
                    ad_type_pks.add(at.pk)
                if not ad.ad_types.all() and ad.ad_type:
                    ad_type_pks.add(ad.ad_type.pk)

        # 3. Export Campaigns for Active Flights
        campaign_pks = set(active_flights.values_list("campaign_id", flat=True))
        campaigns = (
            Campaign.objects.filter(pk__in=campaign_pks)
            .select_related("advertiser")
            .order_by("slug")
        )

        buffer.write(f"-- Campaigns ({campaigns.count()})\n")
        for campaign in campaigns:
            adv_name = campaign.advertiser.name if campaign.advertiser else ""
            logo = (
                campaign.advertiser.advertiser_logo.url
                if campaign.advertiser and campaign.advertiser.advertiser_logo
                else None
            )
            sql = (
                "INSERT OR REPLACE INTO campaigns ("
                "slug, advertiser_name, campaign_type, logo"
                ") VALUES ("
                f"{sql_quote(campaign.slug)}, {sql_quote(adv_name)}, "
                f"{sql_quote(campaign.campaign_type)}, {sql_quote(logo)}"
                ");\n"
            )
            buffer.write(sql)

        buffer.write("\n")

        # 4. Export Ad Types
        ad_types = AdType.objects.filter(pk__in=ad_type_pks).order_by("slug")
        buffer.write(f"-- Ad Types ({ad_types.count()})\n")
        for ad_type in ad_types:
            template_str = ad_type.template or ""
            sql = (
                "INSERT OR REPLACE INTO ad_types ("
                "slug, name, template"
                ") VALUES ("
                f"{sql_quote(ad_type.slug)}, {sql_quote(ad_type.name)}, {sql_quote(template_str)}"
                ");\n"
            )
            buffer.write(sql)

        buffer.write("\n")

        # 5. Export Active Flights
        buffer.write(f"-- Flights ({active_flights.count()})\n")
        for flight in active_flights:
            target_geos_set = set(
                [
                    g.upper()
                    for g in (flight.included_countries + flight.included_regions)
                ]
            )
            target_geos_str = " ".join(sorted(target_geos_set))

            target_topics_set = set(
                [t.lower() for t in (flight.included_topics + flight.included_keywords)]
            )
            target_topics_str = " ".join(sorted(target_topics_set))

            flight_logo = flight.flight_logo.url if flight.flight_logo else None
            pacing_interval = flight.pacing_interval or Flight.DEFAULT_PACING_INTERVAL
            clicks_needed = flight.weighted_clicks_needed_this_interval()

            sql = (
                "INSERT OR REPLACE INTO flights ("
                "slug, campaign_slug, name, priority, target_geos, target_topics, logo, "
                "pacing_interval, weighted_clicks_needed_this_interval, active"
                ") VALUES ("
                f"{sql_quote(flight.slug)}, {sql_quote(flight.campaign.slug)}, {sql_quote(flight.name)}, "
                f"{sql_quote(flight.priority_multiplier)}, {sql_quote(target_geos_str)}, "
                f"{sql_quote(target_topics_str)}, {sql_quote(flight_logo)}, "
                f"{sql_quote(pacing_interval)}, {sql_quote(clicks_needed)}, {sql_quote(1)}"
                ");\n"
            )
            buffer.write(sql)

        buffer.write("\n")

        # 6. Export Advertisements
        # Deduplicate ads if any overlap
        unique_ads_dict = {ad.pk: ad for ad in live_ads_list}
        unique_ads = sorted(unique_ads_dict.values(), key=lambda a: a.slug)

        buffer.write(f"-- Advertisements ({len(unique_ads)})\n")
        for ad in unique_ads:
            first_type = ad.ad_types.first() or ad.ad_type

            text_content = ad.text or ""
            if ad.content:
                body_content = ad.content
            elif ad.text:
                body_content = html.unescape(bleach.clean(ad.text, tags=[], strip=True))
            else:
                body_content = ""

            try:
                html_content = ad.render_ad(first_type, click_url=ad.link)
            except Exception:
                html_content = ""

            ad_image = ad.image.url if ad.image else None

            sql = (
                "INSERT OR REPLACE INTO advertisements ("
                "id, slug, flight_slug, title, text_content, body_content, headline, cta, "
                "image, html_content, destination_url, active"
                ") VALUES ("
                f"{sql_quote(ad.pk)}, {sql_quote(ad.slug)}, {sql_quote(ad.flight.slug)}, "
                f"{sql_quote(ad.name)}, {sql_quote(text_content)}, {sql_quote(body_content)}, "
                f"{sql_quote(ad.headline)}, {sql_quote(ad.cta)}, {sql_quote(ad_image)}, {sql_quote(html_content)}, "
                f"{sql_quote(ad.link)}, {sql_quote(1)}"
                ");\n"
            )
            buffer.write(sql)

        buffer.write("\n")

        # 7. Export Advertisement Ad Types
        ad_type_links = []
        for ad in unique_ads:
            ad_types_for_ad = list(ad.ad_types.all())
            if not ad_types_for_ad and ad.ad_type:
                ad_types_for_ad = [ad.ad_type]
            for at in sorted(ad_types_for_ad, key=lambda x: x.slug):
                ad_type_links.append((ad.id, at.slug))

        buffer.write(f"-- Advertisement Ad Types ({len(ad_type_links)})\n")
        for ad_id, ad_type_slug in ad_type_links:
            sql = (
                "INSERT OR REPLACE INTO advertisement_ad_types ("
                "ad_id, ad_type_slug"
                ") VALUES ("
                f"{sql_quote(ad_id)}, {sql_quote(ad_type_slug)}"
                ");\n"
            )
            buffer.write(sql)

        buffer.write("\n")

        # Optional: Export AnalyzedUrls if adserver.analyzer is active
        if "adserver.analyzer" in settings.INSTALLED_APPS:
            try:
                AnalyzedUrl = apps.get_model("adserver_analyzer", "AnalyzedUrl")
                analyzed_urls = (
                    AnalyzedUrl.objects.exclude(keywords=None)
                    .filter(last_analyzed_date__isnull=False)
                    .order_by("pk")[:5000]
                )

                if analyzed_urls.exists():
                    buffer.write(f"-- URLs ({analyzed_urls.count()})\n")
                    for aurl in analyzed_urls:
                        url_hash = hashlib.sha256(
                            aurl.url.strip().encode("utf-8")
                        ).hexdigest()
                        domain = aurl.domain or get_domain_from_url(aurl.url)
                        analyzed_at = aurl.last_analyzed_date.strftime("%Y-%m-%d")
                        tags = (
                            " ".join(aurl.keywords)
                            if isinstance(aurl.keywords, list)
                            else ""
                        )

                        sql = (
                            "INSERT OR REPLACE INTO urls ("
                            "url_hash, url, domain, analyzed_at, tags"
                            ") VALUES ("
                            f"{sql_quote(url_hash)}, {sql_quote(aurl.url)}, {sql_quote(domain)}, "
                            f"{sql_quote(analyzed_at)}, {sql_quote(tags)}"
                            ");\n"
                        )
                        buffer.write(sql)
            except Exception as exc:
                log.warning("Could not export AnalyzedUrl records: %s", exc)

        content = buffer.getvalue()
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(content)
            self.stdout.write(
                self.style.SUCCESS(f"Successfully exported SQL to {output_file}")
            )
        else:
            self.stdout.write(content, ending="")
