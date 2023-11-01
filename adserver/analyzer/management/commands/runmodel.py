"""Run the ML model on the specified URLs."""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.validators import URLValidator
from django.utils.translation import gettext_lazy as _

from ...utils import get_url_analyzer_backends


class Command(BaseCommand):

    """Run the ML model on the specified URLs."""

    help = "Run the ML model on the specified URLs. Results are not stored to the database."

    def add_arguments(self, parser):
        """Add command line args for this command."""
        parser.add_argument(
            "urls",
            nargs="+",
            help=_("URL to run against"),
        )

    def handle(self, *args, **kwargs):
        """Entrypoint to the command."""
        self.stdout.write(
            _("Using the model(s) from %s") % settings.ADSERVER_ANALYZER_BACKEND
        )

        for url in kwargs["urls"]:
            # raises ValidationError on an invalid URL
            if not URLValidator()(url):
                self.handle_url(url)

    def handle_url(self, url):
        """Dump questions from metabase to a file."""
        self.stdout.write(_("Running against %s") % url)

        keywords = []
        for backend in get_url_analyzer_backends():
            backend_instance = backend(url)
            analyzed_keywords = backend_instance.analyze()
            self.stdout.write(
                _("Keywords from '%s': %s") % (backend.__name__, analyzed_keywords)
            )

            if analyzed_keywords:
                keywords.extend(analyzed_keywords)

        self.stdout.write(_("Keywords/topics: %s") % keywords)
