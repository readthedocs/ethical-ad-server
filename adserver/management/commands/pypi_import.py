"""Import data from Python API"""
import argparse
import getpass
import json
import os
from io import BytesIO

import requests
from django.conf import settings
from django.core.files import File
from django.core.management import CommandError
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from django.utils.translation import ugettext_lazy as _

from adserver.models import AdType
from adserver.models import Advertisement
from adserver.models import Flight


class Command(BaseCommand):

    """Import data for Python"""

    help = "Import data for Python"

    def add_arguments(self, parser):
        """Add command line args for this command."""
        parser.add_argument(
            "-s",
            "--sync",
            action="store_true",
            default=False,
            help=_("Sync data, including deleting old data"),
        )

        parser.add_argument(
            "-i",
            "--images",
            action="store_true",
            default=False,
            help=_("Check images in dry-run"),
        )

    def handle(self, *args, **kwargs):
        """Entrypoint to the command."""

        api_token = os.environ.get("PYTHON_API_TOKEN")
        api_url = os.environ.get("PYTHON_API_URL")
        sync = kwargs["sync"]

        if not api_url and api_token:
            raise CommandError(
                _(
                    "PYTHON_API_TOKEN & PYTHON_API_URL env var needed to run this command"
                )
            )

        if not sync:
            self.stdout.write("DRY RUN: Specify --sync to actually write data")

        # State
        valid_ads = set()
        # Ad types
        psf_ad = AdType.objects.get(slug="psf")
        image_only_ad = AdType.objects.get(slug="psf-image-only")
        # Flights
        sidebar = Flight.objects.get(slug="pypi-sidebar")
        sponsors = Flight.objects.get(slug="pypi-sponsors")

        response = requests.get(
            api_url,
            headers={"Authorization": f"Token {api_token}"},
        )

        for item in response.json():
            self.stdout.write("Processing: " + item["sponsor"])
            try:
                if sync or (not sync and kwargs["images"]):
                    url = item["logo"]
                    image_response = requests.get(url, timeout=5)
                    image_response.raise_for_status()
                    image = File(
                        BytesIO(image_response.content), name=url[url.rfind("/") + 1 :]
                    )
            except:
                self.stdout.write("WARNING: No ad image: %s" % item)
                continue

            if item["flight"] == "sidebar":
                flight = sidebar
            elif item["flight"] == "sponsors":
                flight = sponsors
            else:
                self.stdout.write("WARNING: No Active Flight Data: %s" % item)
                continue

            name = f"{item['sponsor']} ({flight.slug})"

            if sync:
                self.stdout.write(f"Syncing: {name}")
                ad, created = Advertisement.objects.get_or_create(
                    name=name,
                    slug=slugify(name),
                    flight=flight,
                )
                if created:
                    self.stdout.write(f"NEW SPONSOR: Created new sponsor {ad}")

                # Update things that might change
                ad.image = image
                ad.text = item["description"]
                ad.link = item["sponsor_url"]
                ad.live = True
                ad.ad_types.add(psf_ad)
                ad.ad_types.add(image_only_ad)
                ad.save()
            else:
                # Try to get the ad if it exists to add to valid_ads
                try:
                    ad = Advertisement.objects.get(
                        name=name,
                        slug=slugify(name),
                        flight=flight,
                    )
                except Advertisement.DoesNotExist:
                    self.stdout.write(f"Failed to get ad for {name}")
                    continue

            valid_ads.add(ad)

        for iterated_ad in Advertisement.objects.filter(
            flight__campaign__advertiser__slug="psf"
        ):
            if iterated_ad not in valid_ads:
                if sync:
                    self.stdout.write(f"Deactivating invalid ad: {iterated_ad}")
                    iterated_ad.live = False
                    iterated_ad.save()
                else:
                    self.stdout.write(f"Invalid ad will be deactivated: {iterated_ad}")
            else:
                self.stdout.write(f"Keeping ad: {iterated_ad}")
