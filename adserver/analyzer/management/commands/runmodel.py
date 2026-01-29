"""Run the ML model on the specified URLs."""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.validators import URLValidator
from django.utils.module_loading import import_string
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
        parser.add_argument(
            "--backend",
            dest="backend",
            default=None,
            help=_("Specifies a single backend to use for analysis (dotted path)"),
        )

    def handle(self, *args, **kwargs):
        """Entrypoint to the command."""
        backend_path = kwargs.get("backend")
        if backend_path:
            self.stdout.write(_("Using the specified backend: %s") % backend_path)
            self.backends = [import_string(backend_path)]
        else:
            self.stdout.write(
                _("Using the model(s) from %s") % settings.ADSERVER_ANALYZER_BACKEND
            )
            self.backends = list(get_url_analyzer_backends())

        for url in kwargs["urls"]:
            # raises ValidationError on an invalid URL
            if not URLValidator()(url):
                self.handle_url(url)

    def handle_url(self, url):
        """Dump questions from metabase to a file."""
        self.stdout.write(_("Running against %s") % url)

        keywords = []
        for backend in self.backends:
            backend_instance = backend(url)
            response = backend_instance.fetch()
            if not response:
                continue

            analyzed_keywords = backend_instance.analyze(response)
            self.stdout.write(
                _("Keywords from '%s': %s") % (backend.__name__, analyzed_keywords)
            )

            if analyzed_keywords:
                keywords.extend(analyzed_keywords)

        self.stdout.write(_("Keywords/topics: %s") % keywords)
