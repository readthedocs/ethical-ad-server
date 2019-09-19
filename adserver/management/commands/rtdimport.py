"""
Import advertising database data from a Read the Docs data dump.

This adds records from the RTD data dump to the database.
It is advisable to wipe the ad server database before running
as this imports data by ID including primary keys.

Imports from a data dump (on RTD servers) created with:

    $ ./manage.py dumpdata --indent=1 donate > /tmp/ads-data.json

This command is run (on the ad server):

    $ ./manage.py rtdimport ads-data.json
"""
import argparse
import json
from io import BytesIO

import requests
from django.core.files import File
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date
from django.utils.dateparse import parse_datetime
from requests.adapters import HTTPAdapter

from ...constants import PAID_CAMPAIGN
from ...models import AdImpression
from ...models import AdType
from ...models import Advertisement
from ...models import Advertiser
from ...models import Campaign
from ...models import Click
from ...models import Flight
from ...models import Publisher


class Command(BaseCommand):

    """Management command to import advertising DB data from a Read the Docs data dump."""

    help = "Import advertising DB data from a Read the Docs data dump"

    def add_arguments(self, parser):
        parser.add_argument("dumpfile", nargs="+", type=argparse.FileType("r"))

    def handle(self, *args, **options):
        for fp in options["dumpfile"]:
            self.stdout.write(f"Loading data from {fp.name}...")
            try:
                records = json.load(fp)
            except json.JSONDecodeError:
                self.stderr.write(self.style.ERROR(f"Invalid JSON in {fp.name}"))
                continue

            self.import_campaigns(
                [r for r in records if r["model"] == "donate.campaign"]
            )
            self.import_flights([r for r in records if r["model"] == "donate.flight"])
            self.import_advertisements(
                [r for r in records if r["model"] == "donate.supporterpromo"]
            )
            self.import_impressions(
                [r for r in records if r["model"] == "donate.promoimpressions"]
            )
            self.import_clicks([r for r in records if r["model"] == "donate.click"])

    def _get_publisher(self):
        publisher, _ = Publisher.objects.get_or_create(
            slug="readthedocs", defaults={"name": "Read the Docs"}
        )
        return publisher

    def import_campaigns(self, campaign_data):
        """Imports campaigns and creates an advertiser for each one."""
        publisher = self._get_publisher()

        for data in campaign_data:
            campaign_type = data["fields"]["campaign_type"]

            # Only create an advertiser for paid campaigns
            if campaign_type == PAID_CAMPAIGN:
                advertiser = Advertiser.objects.create(
                    name=data["fields"]["name"], slug=data["fields"]["slug"]
                )
            else:
                advertiser = None

            # Campaigns have to be created before the many-many
            # with publishers can be saved
            campaign = Campaign(
                pk=data["pk"],
                name=data["fields"]["name"],
                slug=data["fields"]["slug"],
                campaign_type=campaign_type,
                max_sale_value=data["fields"]["max_sale_value"],
                advertiser=advertiser,
            )
            campaign.save()
            campaign.publishers.add(publisher)

        self.stdout.write(
            self.style.SUCCESS(f"- Imported {len(campaign_data)} campaigns/advertisers")
        )

    def import_flights(self, flight_data):
        """Imports flights."""
        flights = []
        for data in flight_data:
            flights.append(
                Flight(
                    pk=data["pk"],
                    name=data["fields"]["name"],
                    slug=data["fields"]["slug"],
                    live=data["fields"]["live"],
                    priority_multiplier=data["fields"]["priority_multiplier"],
                    cpc=data["fields"]["cpc"],
                    cpm=data["fields"]["cpm"],
                    sold_clicks=data["fields"]["sold_clicks"],
                    sold_impressions=data["fields"]["sold_impressions"],
                    campaign_id=data["fields"]["campaign"],
                    start_date=parse_date(data["fields"]["start_date"]),
                    end_date=parse_date(data["fields"]["end_date"]),
                    targeting_parameters=json.loads(
                        data["fields"]["targeting_parameters"]
                    )
                    if data["fields"]["targeting_parameters"]
                    else {},
                )
            )

        Flight.objects.bulk_create(flights)
        self.stdout.write(self.style.SUCCESS(f"- Imported {len(flights)} flights"))

    def import_advertisements(self, advertisements_data):
        """Imports advertisements."""
        publisher = self._get_publisher()

        ad_type_mapping = {
            "doc": AdType.objects.create(
                name="RTD Sidebar",
                slug="readthedocs-sidebar",
                has_image=True,  # Can't enforce image sizes due to bad data
                has_text=True,
                max_text_length=150,  # Many ads exceed the "allowed" 80
                publisher=publisher,
            ),
            "site-footer": AdType.objects.create(
                name="RTD Footer",
                slug="readthedocs-footer",
                has_image=True,
                image_width=240,
                image_height=180,
                has_text=True,
                max_text_length=300,
                publisher=publisher,
            ),
            "fixed-footer": AdType.objects.create(
                name="RTD Fixed Footer",
                slug="readthedocs-fixed-footer",
                has_image=False,
                has_text=True,
                max_text_length=100,
                publisher=publisher,
            ),
            # There are two "error" ads but they are old and problematic
            # The images are SVGs (can't be stored in an ImageField)
            "error": None,
        }

        # Prevent requesting the same image twice
        image_cache = {}

        # Retry fetching ads
        session = requests.Session()
        session.mount("https://assets.readthedocs.org", HTTPAdapter(max_retries=3))

        advertisements = []
        for data in advertisements_data:
            image = None
            url = data["fields"]["image"]
            if url and url in image_cache:
                image = image_cache[url]
            elif url and not url.endswith(".svg"):
                response = session.get(url, timeout=5)
                response.raise_for_status()
                image = File(BytesIO(response.content), name=url[url.rfind("/") + 1 :])
                image_cache[url] = image

            advertisements.append(
                Advertisement(
                    pk=data["pk"],
                    name=data["fields"]["name"],
                    slug=data["fields"]["analytics_id"],
                    live=data["fields"]["live"],
                    text=data["fields"]["text"],
                    link=data["fields"]["link"],
                    image=image,
                    ad_type=ad_type_mapping[data["fields"]["display_type"]],
                    flight_id=data["fields"]["flight"],
                )
            )

        Advertisement.objects.bulk_create(advertisements)
        self.stdout.write(
            self.style.SUCCESS(f"- Imported {len(advertisements)} advertisements")
        )

    def import_impressions(self, impressions_data):
        """Import impression data."""
        publisher = self._get_publisher()

        impressions = []
        for data in impressions_data:
            impressions.append(
                AdImpression(
                    pk=data["pk"],
                    date=parse_date(data["fields"]["date"]),
                    publisher=publisher,
                    advertisement_id=data["fields"]["promo"],
                    offers=data["fields"]["offers"],
                    views=data["fields"]["views"],
                    clicks=data["fields"]["clicks"],
                )
            )

        AdImpression.objects.bulk_create(impressions)
        self.stdout.write(
            self.style.SUCCESS(f"- Imported {len(impressions)} impressions")
        )

    def import_clicks(self, clicks_data):
        """Import click data."""
        publisher = self._get_publisher()

        clicks = []
        for data in clicks_data:
            clicks.append(
                Click(
                    pk=data["pk"],
                    date=parse_datetime(data["fields"]["date"]),
                    publisher=publisher,
                    advertisement_id=data["fields"]["promo"],
                    ip=data["fields"]["ip"],
                    user_agent=data["fields"]["user_agent"],
                    client_id=data["fields"]["client_id"],
                    country=data["fields"]["country"],
                    url=data["fields"]["url"],
                    browser_family=data["fields"]["browser_family"],
                    os_family=data["fields"]["os_family"],
                    is_bot=data["fields"]["is_bot"],
                    is_mobile=data["fields"]["is_mobile"],
                )
            )

        Click.objects.bulk_create(clicks)
        self.stdout.write(self.style.SUCCESS(f"- Imported {len(clicks)} clicks"))
