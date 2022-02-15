import logging
import os
from io import BytesIO

import requests
from django.core.exceptions import ImproperlyConfigured
from django.core.files import File
from django.utils.text import slugify
from django.utils.translation import ugettext_lazy as _

from adserver.models import AdType
from adserver.models import Advertisement
from adserver.models import Flight

log = logging.getLogger(__name__)  # noqa


def run_import(sync=False, images=False):
    """
    An importer for the PSF Advertiser account.

    This currently syncs a few different things:

    * PyPI Sidebar sponsors
    * PyPI Sponsors
    * PSF Sponsors
    * PSF Jobs
    * Pycon Sponsors

    This list will get updated as the sponsorship expands.

    :arg: sync: Actually write data to the Database.
    :arg: images: Test images when not doing a full sync.
    """

    api_token = os.environ.get("PYTHON_API_TOKEN")
    api_url = os.environ.get("PYTHON_API_URL")

    if not api_url and api_token:
        raise ImproperlyConfigured(
            "PYTHON_API_TOKEN & PYTHON_API_URL env var needed to run this command"
        )

    if not sync:
        log.warning("DRY RUN: Specify --sync to actually write data")

    # State
    valid_ads = set()
    # Ad types
    psf_ad = AdType.objects.get(slug="psf")
    image_only_ad = AdType.objects.get(slug="psf-image-only")
    # Flights
    pypi_sidebar = Flight.objects.get(slug="pypi-sidebar")
    pypi_sponsors = Flight.objects.get(slug="pypi-sponsors")
    psf_sponsors = Flight.objects.get(slug="psf-sponsors")
    psf_jobs = Flight.objects.get(slug="psf-jobs")
    pycon_sponsors = Flight.objects.get(slug="pycon-sponsors")

    response = requests.get(
        api_url,
        headers={"Authorization": f"Token {api_token}"},
    )

    for item in response.json():
        log.debug("Processing: " + item["sponsor"])
        try:
            # Only run this code when we're either syncing, or we specifically want images.
            # This is because gathering images is the slowest part of this process.
            if sync or images:
                url = item["logo"]
                image_response = requests.get(url, timeout=5)
                image_response.raise_for_status()
                image = File(
                    BytesIO(image_response.content), name=url[url.rfind("/") + 1 :]
                )
        except:
            log.exception("WARNING: No ad image: %s" % item)
            continue

        if item["flight"] == "sidebar":
            flight = pypi_sidebar
        elif item["flight"] == "sponsors" and item["publisher"] == "pypi":
            flight = pypi_sponsors
        elif item["flight"] == "sponsors" and item["publisher"] == "psf":
            flight = psf_sponsors
        elif item["flight"] == "jobs" and item["publisher"] == "psf":
            flight = psf_jobs
        elif item["flight"] == "sponsors" and item["publisher"] == "pycon":
            flight = pycon_sponsors
        else:
            log.warning("WARNING: No Active Flight Data: %s" % item)
            continue

        name = f"{item['sponsor']} ({flight.slug})"

        if sync:
            log.info(f"Syncing: {name}")
            ad, created = Advertisement.objects.get_or_create(
                name=name,
                slug=slugify(name),
                flight=flight,
            )
            if created:
                log.info(f"NEW SPONSOR: Created new sponsor {ad}")

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
                log.warning(f"Failed to get ad for {name}")
                continue

        valid_ads.add(ad)

    for iterated_ad in Advertisement.objects.filter(
        flight__campaign__advertiser__slug="psf", live=True
    ):
        if iterated_ad not in valid_ads:
            if sync:
                log.info(f"Deactivating invalid ad: {iterated_ad}")
                iterated_ad.live = False
                iterated_ad.save()
            else:
                log.info(f"Invalid ad will be deactivated: {iterated_ad}")
        else:
            log.debug(f"Keeping ad: {iterated_ad}")
