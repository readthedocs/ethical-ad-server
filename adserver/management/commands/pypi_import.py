"""Import data from Python API."""

from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _

from adserver.importers import psf


class Command(BaseCommand):
    """Import data for PSF."""

    help = "Import data for PSF"

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
        psf.run_import(sync=kwargs["sync"], images=kwargs["images"])
