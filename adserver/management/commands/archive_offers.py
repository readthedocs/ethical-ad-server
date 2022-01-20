"""
Archives old offers to CSV files.

The offers table can get very large
and it's important for performance to keep it as small as possible.
As a result, archiving old offers can have a good effect on performance.
This management command archives old offers to CSV files, zips them,
can copy them to remote storage (settings.BACKUPS_STORAGE)
and with a passed flag can delete the archives from the DB.
"""
import datetime
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files.storage import get_storage_class
from django.core.management import CommandError
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _


class Command(BaseCommand):

    """Management command to help archive offers."""

    help = "Archives offers in CSV form from the database to files: one per day."

    default_output_dir = "/tmp"
    default_end_date = (timezone.now() - datetime.timedelta(days=90)).date()
    default_start_date = default_end_date - datetime.timedelta(days=30)

    storage_output_dir = "offers/"

    # This will be populated from the default or command line args
    output_dir = None

    def _from_isoformat(self, date_str):
        """
        Returns a datetime.date objects for a given date string.

        This method was added to datetime.date in Python 3.7. Use that after upgrading.
        """
        return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()

    def add_arguments(self, parser):
        """Add command line args for this command."""
        parser.add_argument(
            "-o",
            "--output-dir",
            default=self.default_output_dir,
            type=str,
            help=_("Directory to write output files (a subdir will be created)"),
        )
        parser.add_argument(
            "-d",
            "--delete-offers",
            action="store_true",
            default=False,
            help=_(
                "Delete offers after archiving (requires successful copying to remote backups)"
            ),
        )
        parser.add_argument(
            "-s",
            "--start-date",
            default=self.default_start_date,
            type=self._from_isoformat,
            help=_("Start date to dump offers (default 7 days ago)"),
        )
        parser.add_argument(
            "-e",
            "--end-date",
            default=self.default_end_date,
            type=self._from_isoformat,
            help=_("End date to dump offers (inclusive, defaults to yesterday)"),
        )

    def handle_archive_day(self, day):
        """Archive a single day of offers to a file."""
        output_file = self.output_dir / f"{day:%Y-%m-%d}-offers.csv"
        zipped_output_file = Path(str(output_file) + ".bz2")
        end_day = day + datetime.timedelta(days=1)

        self.stdout.write(_("Archiving %s to %s...") % (day, output_file))

        # Using the date params as an f-string is suboptimal but these are validated
        query = f"""
            COPY (
                SELECT * FROM adserver_offer
                WHERE date >= '{day:%Y-%m-%d}' AND date < '{end_day:%Y-%m-%d}'
                ORDER BY date
            ) TO STDOUT WITH CSV HEADER"""
        with connection[settings.REPLICA_SLUG].cursor() as cursor:
            with open(output_file, "wb") as fd:
                # https://www.psycopg.org/docs/cursor.html#cursor.copy_expert
                cursor.copy_expert(query, fd)

        # This will be off by one because the CSV contains a header row
        self.stdout.write(_("Running `wc -l %s`...") % output_file)
        self.stdout.write(
            subprocess.check_output(
                ["wc", "-l", str(output_file)],
                stderr=subprocess.STDOUT,
                encoding="utf-8",
            )
        )

        self.stdout.write(_("Compressing %s...") % output_file)
        self.stdout.write(
            subprocess.check_output(
                ["bzip2", str(output_file)],
                stderr=subprocess.STDOUT,
                encoding="utf-8",
            )
        )

        # Azure storage automatically stores the md5sum in the ContentMd5 header/property
        # You can verify it after copying with:
        #  echo -n MD5HEXSUM | xxd -p -r | base64
        self.stdout.write(_("MD5 summing %s...") % zipped_output_file)
        self.stdout.write(
            subprocess.check_output(
                ["md5sum", str(zipped_output_file)],
                stderr=subprocess.STDOUT,
                encoding="utf-8",
            )
        )

        self.stdout.write(self.style.SUCCESS(_("Successfully archived %s.") % day))

        return zipped_output_file

    def copy_offer_dump(self, archive_filepath):
        """Copy offer CSV files to settings.BACKUPS_STORAGE."""
        if not hasattr(settings, "BACKUPS_STORAGE"):
            self.stdout.write(
                self.style.WARNING(
                    _(
                        "Skipping copying offers to backups (BACKUPS_STORAGE is not defined)..."
                    )
                )
            )
            return

        storage = get_storage_class(settings.BACKUPS_STORAGE)()

        storage_path = self.storage_output_dir + archive_filepath.name
        self.stdout.write(_("Copying offers (%s) to backups...") % archive_filepath)
        if storage.exists(storage_path):
            self.stdout.write(
                self.style.WARNING(_("- %s already exists in backups") % storage_path)
            )
        with open(archive_filepath, "rb") as fd:
            storage.save(storage_path, fd)

        self.stdout.write(
            self.style.SUCCESS(
                _("Successfully copied %s to backups.") % archive_filepath
            )
        )

    def delete_offers(self, day):
        """Deletes offers from the database (requires them to be copied to settings.BACKUPS_STORAGE)."""
        if not hasattr(settings, "BACKUPS_STORAGE"):
            self.stdout.write(
                self.style.WARNING(
                    _("Skipping deleting archived offers (backups weren't copied)...")
                )
            )
            return

        self.stdout.write(_("Deleting archived offers for %s...") % day)

        end_day = day + datetime.timedelta(days=1)
        query = "DELETE FROM adserver_offer WHERE date >= %s AND date < %s"

        self.stdout.write(_("- Executing SQL:"))
        self.stdout.write(query % (day, end_day))

        # Always delete from the default.
        with connection["default"].cursor() as cursor:
            # Offers are normally immutable so the delete has to be run as raw sql
            cursor.execute(
                query,
                [day, end_day],
            )
            deleted_offers = cursor.fetchone()

        self.stdout.write(
            self.style.SUCCESS(_("Successfully removed %d offers.") % deleted_offers)
        )

    def update_db_stats(self):
        """Updates DB stats after these changes."""
        self.stdout.write(_("Updating database statistics..."))
        with connection.cursor() as cursor:
            # Run an analyze so the DB statistics are up to date
            # This will help future queries run quickly after this change
            cursor.execute("ANALYZE VERBOSE adserver_offer;")

        self.stdout.write(self.style.SUCCESS(_("Successfully updated DB statistics.")))

    def handle(self, *args, **kwargs):
        """Entrypoint to the command."""
        path = Path(kwargs["output_dir"])
        if not path.exists() or not path.is_dir():
            raise CommandError(_("Path %s does not exist") % str(path))

        # Create a new archived-offers temporary directory to hold output
        new_dir = tempfile.mkdtemp(dir=path, prefix="archived-offers_")
        self.output_dir = Path(new_dir)

        self.stdout.write(
            self.style.SUCCESS(_("Archiving offers to %s...") % self.output_dir)
        )

        day = kwargs["start_date"]
        while day <= kwargs["end_date"]:
            archive_filepath = self.handle_archive_day(day)
            self.copy_offer_dump(archive_filepath)
            if kwargs["delete_offers"]:
                self.delete_offers(day)

            day += datetime.timedelta(days=1)

        if kwargs["delete_offers"]:
            # Update DB stats if we deleted anything
            self.update_db_stats()
