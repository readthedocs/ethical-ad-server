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
import os
from collections import defaultdict
from io import BytesIO

import requests
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import models
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
    BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))

    BATCH_SIZE = 500

    # Maps programming languages as they appear for flight targeting
    # To a proper keyword respresentation
    PROGRAMMING_LANGUAGE_MAPPING = {
        "c": "c",
        "coffee": "coffeescript",
        "cpp": "c++",
        "csharp": "c#",
        "css": "css",
        "go": "go",
        "groovy": "groovy",
        "haskell": "haskell",
        "java": "java",
        "js": "javascript",
        "julia": "julia",
        "lua": "lua",
        "objc": "objective-c",
        "other": "other",
        "perl": "perl",
        "php": "php",
        "py": "python",
        "r": "r",
        "ruby": "ruby",
        "scala": "scala",
        "swift": "swift",
        "ts": "typescript",
        "vb": "visual-basic",
        "words": "only-words",
    }

    def add_arguments(self, parser):
        parser.add_argument("dumpfile", nargs="+", type=argparse.FileType("r"))

        parser.add_argument(
            "--skip-impressions",
            action="store_true",
            default=False,
            help="Skip importing impressions which can be a large amount of data",
        )

    def handle(self, *args, **options):
        for fp in options["dumpfile"]:
            self.stdout.write(f"Loading data from {fp.name}...")
            try:
                records = json.load(fp)
            except json.JSONDecodeError:
                self.stderr.write(self.style.ERROR(f"Invalid JSON in {fp.name}"))
                continue

            # Get a mapping of project IDs to publishers
            # This is used later when importing impressions and clicks
            publisher_mapping = self.import_publishers(
                r for r in records if r["model"] == "donate.projectgroup"
            )

            # Get the "readthedocs" publisher
            readthedocs_publisher = self._get_readthedocs_publisher(publisher_mapping)
            if not readthedocs_publisher:
                self.stderr.write(
                    self.style.ERROR(
                        f"  Can't find the 'readthedocs' publisher in {fp.name}"
                    )
                )
                continue

            self.import_campaigns(
                (r for r in records if r["model"] == "donate.campaign"),
                list(set(publisher_mapping.values())),
            )
            self.import_flights(r for r in records if r["model"] == "donate.flight")
            self.import_advertisements(
                r for r in records if r["model"] == "donate.supporterpromo"
            )
            self.import_clicks(
                (r for r in records if r["model"] == "donate.click"),
                publisher_mapping,
                readthedocs_publisher,
            )

            if not options["skip_impressions"]:
                revshare_impressions = self.import_revshare_impressions(
                    (r for r in records if r["model"] == "donate.projectimpressions"),
                    publisher_mapping,
                    readthedocs_publisher,
                )
                self.import_readthedocs_impressions(
                    (r for r in records if r["model"] == "donate.promoimpressions"),
                    revshare_impressions,
                    readthedocs_publisher,
                )

                self.calculate_flight_totals()

    def _get_readthedocs_publisher(self, publisher_mapping):
        readthedocs_publisher = None
        rtd_publishers = [
            pub for pub in publisher_mapping.values() if pub.slug == "readthedocs"
        ]
        if rtd_publishers:
            readthedocs_publisher = rtd_publishers[0]

        return readthedocs_publisher

    def import_publishers(self, publisher_data):
        """
        Imports publishers from the Read the Docs database.

        Treat project groups as publishers as those are the projects involved in revenue shares.
        One of those project groups is the "readthedocs" group.

        :returns: a mapping of project slugs to publisher objects
        """
        publishers_count = 0
        publisher_mapping = {}
        for data in publisher_data:
            slug = data["fields"]["slug"]

            # Prepend readthedocs- to revshare projects
            # eg. readthedocs-pallets, readthedocs-celery
            if not slug.startswith("readthedocs"):
                slug = "readthedocs-" + slug

            # Publishers need to go one-by-one so because `bulk_create` doesn't set the primary_key
            publisher = Publisher(name=data["fields"]["name"], slug=slug)
            publisher.save()
            publishers_count += 1

            for project_id in data["fields"]["projects"]:
                publisher_mapping[project_id] = publisher

        self.stdout.write(
            self.style.SUCCESS(f"- Imported {publishers_count} publishers")
        )

        return publisher_mapping

    def import_campaigns(self, campaign_data, publishers):
        """Imports campaigns and creates an advertiser for each one."""
        campaigns = 0

        advertiser_readthedocs = Advertiser.objects.create(
            name="Read the Docs", slug="readthedocs"
        )

        for data in campaign_data:
            campaign_type = data["fields"]["campaign_type"]

            # Only create an advertiser for paid campaigns
            if campaign_type == PAID_CAMPAIGN:
                advertiser = Advertiser.objects.create(
                    name=data["fields"]["name"], slug=data["fields"]["slug"]
                )
            else:
                # All house and community ads are by Read the Docs
                advertiser = advertiser_readthedocs

            # Campaigns have to be created before the many-many
            # with publishers can be saved
            campaign = Campaign(
                pk=data["pk"],
                name=data["fields"]["name"],
                slug=data["fields"]["slug"],
                campaign_type=campaign_type,
                advertiser=advertiser,
            )
            campaign.save()
            campaigns += 1
            for publisher in publishers:
                campaign.publishers.add(publisher)

        self.stdout.write(
            self.style.SUCCESS(f"- Imported {campaigns} campaigns/advertisers")
        )

    def import_flights(self, flight_data):
        """Imports flights."""
        flights = []
        for data in flight_data:
            flight_name = data["fields"]["name"]

            # Convert old RTD targeting to always use keywords
            targeting_params = {}
            if data["fields"]["targeting_parameters"]:
                targeting_params = json.loads(data["fields"]["targeting_parameters"])
                targeting_keywords = targeting_params.get("include_keywords", [])
                if "include_programming_languages" in targeting_params:
                    new_keywords = [
                        self.PROGRAMMING_LANGUAGE_MAPPING[lang]
                        for lang in targeting_params["include_programming_languages"]
                    ]
                    targeting_keywords.extend(new_keywords)
                    del targeting_params["include_programming_languages"]
                if "include_projects" in targeting_params:
                    new_keywords = [
                        f"readthedocs-project-{project}"
                        for project in targeting_params["include_projects"]
                    ]
                    targeting_keywords.extend(new_keywords)
                    del targeting_params["include_projects"]

                # Remove unused targeting parameters
                if "exclude_programming_languages" in targeting_params:
                    del targeting_params["exclude_programming_languages"]

                # Save the keywords as the new way to target by language/project/etc.
                if targeting_keywords:
                    targeting_params["include_keywords"] = targeting_keywords

            flights.append(
                Flight(
                    pk=data["pk"],
                    name=flight_name,
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
                    targeting_parameters=targeting_params,
                )
            )

        Flight.objects.bulk_create(flights, batch_size=self.BATCH_SIZE)
        self.stdout.write(self.style.SUCCESS(f"- Imported {len(flights)} flights"))

    def import_advertisements(self, advertisements_data):
        """Imports advertisements."""
        allowed_tags = [
            # Defaults from bleach
            "a",
            "abbr",
            "acronym",
            "b",
            "blockquote",
            "code",
            "em",
            "i",
            "li",
            "ol",
            "strong",
            "ul",
            # Added for RTD
            "br",
            "small",
        ]

        with open(
            os.path.join(self.BASE_DIR, "adtype-templates/readthedocs-sidebar.html"),
            "r",
            encoding="utf-8",
        ) as fd:
            rtd_sidebar_template = fd.read()
        with open(
            os.path.join(self.BASE_DIR, "adtype-templates/readthedocs-footer.html"),
            "r",
            encoding="utf-8",
        ) as fd:
            rtd_footer_template = fd.read()
        with open(
            os.path.join(
                self.BASE_DIR, "adtype-templates/readthedocs-fixedfooter.html"
            ),
            "r",
            encoding="utf-8",
        ) as fd:
            rtd_fixedfooter_template = fd.read()

        ad_type_mapping = {
            "doc": AdType.objects.create(
                name="RTD Sidebar",
                slug="readthedocs-sidebar",
                has_image=True,  # Can't enforce image sizes due to bad data
                has_text=True,
                max_text_length=150,  # Many ads exceed the "allowed" 80
                allowed_html_tags=" ".join(allowed_tags),
                template=rtd_sidebar_template,
            ),
            "site-footer": AdType.objects.create(
                name="RTD Footer",
                slug="readthedocs-footer",
                has_image=True,
                image_width=240,
                image_height=180,
                has_text=True,
                max_text_length=300,
                allowed_html_tags=" ".join(allowed_tags),
                template=rtd_footer_template,
            ),
            "fixed-footer": AdType.objects.create(
                name="RTD Fixed Footer",
                slug="readthedocs-fixed-footer",
                has_image=False,
                has_text=True,
                max_text_length=100,
                allowed_html_tags=" ".join(allowed_tags),
                template=rtd_fixedfooter_template,
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

        advertisements = 0
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

            ad = Advertisement(
                pk=data["pk"],
                name=data["fields"]["name"],
                slug=data["fields"]["analytics_id"],
                live=data["fields"]["live"],
                text=data["fields"]["text"],
                link=data["fields"]["link"],
                image=image,
                flight_id=data["fields"]["flight"],
            )
            ad.save()
            advertisements += 1
            ad.ad_types.add(ad_type_mapping[data["fields"]["display_type"]])

        self.stdout.write(
            self.style.SUCCESS(f"- Imported {advertisements} advertisements")
        )

    def import_clicks(self, clicks_data, publisher_mapping, readthedocs_publisher):
        """Import click data."""
        clicks = []
        for data in clicks_data:
            # Associate the click with a publisher (revshare partner)
            # Or default to associating with Read the Docs
            project = data["fields"]["project"]
            publisher = publisher_mapping.get(project, readthedocs_publisher)

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

        Click.objects.bulk_create(clicks, batch_size=self.BATCH_SIZE)
        self.stdout.write(self.style.SUCCESS(f"- Imported {len(clicks)} clicks"))

    def import_revshare_impressions(
        self, project_impressions_data, publisher_mapping, readthedocs_publisher
    ):
        """
        Import impression data for revshare publishers.

        Compared with the other import methods, this has the most complex logic.
        The best way to reason about this is that the old PromoImpressions model
        has one entry per day/ad combination while the old ProjectImpressions model
        has one entry per project/day/ad combination but only for select revshare projects.
        The new AdImpression model has one entry per publisher/ad/day combination.

        All PromoImpressions that aren't attributed to a project should be associated
        with the "readthedocs" publisher but that is done in ``import_readthedocs_impressions``.
        """
        # Maps "{publisher}_{advertisement}_{date} => impression
        impressions_map = {}

        # Save all impression data for publishers other than "readthedocs"
        for data in project_impressions_data:
            # Associate impression with a publisher (revshare partner)
            project = data["fields"]["project"]
            publisher = publisher_mapping.get(project, None)
            advertisement_id = data["fields"]["promo"]
            date = data["fields"]["date"]

            # Skip unknown projects/publishers, those aren't revshare publishers
            if not publisher or publisher == readthedocs_publisher:
                continue

            key = f"{publisher.id}__{advertisement_id}__{date}"
            if key in impressions_map:
                # Add to the existing impression data for this day
                impressions_map[key].offers += data["fields"]["offers"]
                impressions_map[key].views += data["fields"]["views"]
                impressions_map[key].clicks += data["fields"]["clicks"]
            else:
                # Create new impression data for this day
                impressions_map[key] = AdImpression(
                    date=parse_date(date),
                    publisher=publisher,
                    advertisement_id=advertisement_id,
                    offers=data["fields"]["offers"],
                    views=data["fields"]["views"],
                    clicks=data["fields"]["clicks"],
                )

        impressions = list(impressions_map.values())
        AdImpression.objects.bulk_create(impressions, batch_size=self.BATCH_SIZE)
        self.stdout.write(
            self.style.SUCCESS(
                f"- Imported {len(impressions)} revshare publisher impressions"
            )
        )
        return impressions

    def import_readthedocs_impressions(
        self, overall_impressions_data, revshare_impressions, readthedocs_publisher
    ):
        """
        Import impressions for non-revshare impressions (that is, Read the Docs itself).

        This method takes the overall impression data (from the old PromoImpressions model)
        and subtracts any impressions attributed to a revshare publisher.
        """
        # Maps "{advertisement}_{date} => [matching_impressions]
        revshare_impressions_mapping = defaultdict(list)
        for impression in revshare_impressions:
            key = f"{impression.advertisement_id}__{impression.date}"
            revshare_impressions_mapping[key].append(impression)

        impressions = []
        for data in overall_impressions_data:
            publisher = readthedocs_publisher
            advertisement_id = data["fields"]["promo"]
            date = data["fields"]["date"]
            impression = AdImpression(
                date=parse_date(date),
                publisher=publisher,
                advertisement_id=advertisement_id,
                offers=data["fields"]["offers"],
                views=data["fields"]["views"],
                clicks=data["fields"]["clicks"],
            )

            # Subtract impressions on revshare partners that happened
            # for the same ad/day combination
            key = f"{impression.advertisement_id}__{impression.date}"
            for imp in revshare_impressions_mapping[key]:
                impression.offers -= imp.offers
                impression.views -= imp.views
                impression.clicks -= imp.clicks

            impressions.append(impression)

        AdImpression.objects.bulk_create(impressions, batch_size=self.BATCH_SIZE)
        self.stdout.write(
            self.style.SUCCESS(
                f"- Imported {len(impressions)} Read the Docs impressions"
            )
        )

    def calculate_flight_totals(self):
        for flight in Flight.objects.all().annotate(
            flight_total_clicks=models.Sum(
                models.F("advertisements__impressions__clicks")
            ),
            flight_total_views=models.Sum(
                models.F("advertisements__impressions__views")
            ),
        ):
            flight.total_clicks = flight.flight_total_clicks or 0
            flight.total_views = flight.flight_total_views or 0
            flight.save()

        self.stdout.write(
            self.style.SUCCESS("- Calculated totals across imported flights")
        )
