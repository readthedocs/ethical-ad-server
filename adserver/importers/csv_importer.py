import csv
import logging
import os

from django.core.files import File
from django.utils.text import slugify

from adserver.models import AdType
from adserver.models import Advertisement
from adserver.models import Flight


log = logging.getLogger(__name__)


def run_csv_import(csv_path, image_dir, advertiser_slug, flight_slug, sync=False):
    """
    Import advertisements from a CSV file and a directory of images.

    :param csv_path: Path to the CSV file containing ad data.
    :param image_dir: Path to the directory containing ad images.
    :param advertiser_slug: Slug of the advertiser.
    :param flight_slug: Slug of the flight.
    :param sync: Whether to write data to the database.

    Example usage:
        from adserver.importers.csv_importer import run_csv_import

        run_csv_import(
            csv_path="ads.csv",
            image_dir="images",
            advertiser_slug="ethicalads-community",
            flight_slug="ethicalads-community-open-source-pledge",
            sync=True
        )
    """
    # Resolve relative paths to absolute paths
    csv_path = os.path.abspath(csv_path)
    image_dir = os.path.abspath(image_dir)

    if not os.path.exists(csv_path):
        log.error(f"CSV file not found: {csv_path}")
        return

    if not os.path.exists(image_dir):
        log.error(f"Image directory not found: {image_dir}")
        return

    if not sync:
        log.warning("DRY RUN: Specify --sync to actually write data")

    # State
    valid_ads = set()
    # Ad types
    default_ad_type = AdType.objects.get(slug="default")

    # Fetch the advertiser and flight for the given slugs
    try:
        flight = Flight.objects.get(
            slug=flight_slug, campaign__advertiser__slug=advertiser_slug
        )
    except Flight.DoesNotExist:
        log.error(f"Flight not found: {advertiser_slug}/{flight_slug}")
        return

    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            try:
                name = row["name"]
                image_filename = row["image"]
                text = row["text"]

                image_path = os.path.join(image_dir, image_filename)
                if not os.path.exists(image_path):
                    log.warning(f"Image not found for ad: {name} ({image_filename})")
                    continue

                with open(image_path, "rb") as image_file:
                    image = File(image_file, name=image_filename)

                slug = slugify(name)
                if sync:
                    ad, created = Advertisement.objects.get_or_create(
                        slug=slug, flight=flight
                    )
                    if created:
                        log.info(f"NEW AD: Created new ad {name}")

                    # Update fields
                    ad.name = name
                    ad.image.save(image_filename, image, save=False)
                    ad.text = text
                    ad.live = True
                    ad.ad_types.add(default_ad_type)
                    try:
                        ad.save()
                    except Exception:
                        log.exception(f"Failed to save ad: {name}")
                else:
                    log.info(f"DRY RUN: Would process ad {name}")

                valid_ads.add(slug)

            except KeyError as e:
                log.error(f"Missing required column in CSV: {e}")
            except Exception:
                log.exception(f"Error processing row: {row}")

    # Disable ads no longer in the CSV
    for ad in Advertisement.objects.filter(live=True):
        if ad.slug not in valid_ads:
            if sync:
                log.info(f"Deactivating ad: {ad.name}")
                ad.live = False
                ad.save()
            else:
                log.info(f"DRY RUN: Would deactivate ad: {ad.name}")
