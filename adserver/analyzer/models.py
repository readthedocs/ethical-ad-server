"""Stored results of offline content targeting analysis."""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_extensions.db.models import TimeStampedModel
from jsonfield import JSONField
from simple_history.models import HistoricalRecords

from ..models import Publisher


class AnalyzedUrl(TimeStampedModel):

    """Analyzed keywords for a given URL."""

    # Query parameters ignored by the analyzer
    IGNORE_QUERY_PARAMS = (
        "q",
        "query",
        "search",
    )

    url = models.URLField(
        db_index=True,
        max_length=1024,
        help_text=_(
            "URL of the page being analyzed after certain query parameters are stripped away"
        ),
    )

    publisher = models.ForeignKey(
        Publisher,
        help_text=_("Publisher where this URL appears"),
        on_delete=models.CASCADE,
    )

    # Fields below are updated by the analyzer
    keywords = JSONField(_("Keywords for this URL"), blank=True, null=True)
    last_analyzed_date = models.DateTimeField(
        db_index=True,
        default=None,
        null=True,
        blank=True,
        help_text=_("Last time the ad server analyzed this URL"),
    )
    last_ad_served_date = models.DateTimeField(
        default=None,
        null=True,
        blank=True,
        help_text=_("Last time an ad was served for this URL"),
    )
    visits_since_last_analyzed = models.PositiveIntegerField(
        default=0,
        help_text=_(
            "Number of times ads have been served for this URL since it was last analyzed"
        ),
    )

    history = HistoricalRecords()

    def __str__(self):
        """Simple override."""
        return f"{self.keywords} on {self.url}"
