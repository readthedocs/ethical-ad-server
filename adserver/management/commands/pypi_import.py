"""Import data from Python API"""
import os

from django.core.management import CommandError
from django.core.management.base import BaseCommand
from django.utils.translation import ugettext_lazy as _

from adserver.importers import psf


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

        psf.run_import(sync=kwargs["sync"], images=kwargs["images"])
