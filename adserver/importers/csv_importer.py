import csv
import logging
import os
from io import BytesIO

from django.core.files import File
from django.utils.text import slugify

from adserver.models import AdType
from adserver.models import Advertisement
from adserver.models import Flight


log = logging.getLogger(__name__)


def run_csv_import(csv_path, image_dir, link, advertiser_slug, flight_slug, sync=False):
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
        csv_path="ad-data.txt",
        image_dir="photos",
        link="https://opensourcepledge.com/?ref=ethicalads-community",
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
    default_ad_type = AdType.objects.get(slug="image-v1")

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
                headline = row.get("headline", "")  # Extract headline, default to empty
                text = row["text"]
                cta = row.get("cta", "")  # Extract call-to-action, default to empty

                image_path = os.path.join(image_dir, image_filename)
                if not os.path.exists(image_path):
                    log.warning(f"Image not found for ad: {name} ({image_filename})")
                    continue

                # Open the image file using BytesIO for consistency
                with open(image_path, "rb") as image_file:
                    image = File(BytesIO(image_file.read()), name=image_filename)
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
                        if headline or cta:
                            ad.headline = headline
                            ad.content = text
                            ad.cta = cta
                            ad.text = ""
                        else:
                            ad.text = text
                            ad.headline = ""
                            ad.cta = ""
                            ad.content = ""
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
