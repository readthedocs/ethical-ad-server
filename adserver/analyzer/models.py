"""Stored results of offline content targeting analysis."""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_extensions.db.models import TimeStampedModel
from jsonfield import JSONField
from pgvector.django import VectorField
from simple_history.models import HistoricalRecords

from ..models import Publisher
from .validators import KeywordsValidator


class AnalyzedUrl(TimeStampedModel):

    """Analyzed keywords for a given URL."""

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
    keywords = JSONField(
        _("Keywords for this URL"),
        blank=True,
        null=True,
        validators=[KeywordsValidator()],
    )
    last_analyzed_date = models.DateTimeField(
        db_index=True,
        default=None,
        null=True,
        blank=True,
        help_text=_("Last time the ad server analyzed this URL"),
    )
    # This is only accurate to the day
    last_ad_served_date = models.DateField(
        default=None,
        null=True,
        blank=True,
        help_text=_("Last date an ad was served for this URL"),
    )
    visits_since_last_analyzed = models.PositiveIntegerField(
        default=0,
        help_text=_(
            "Number of times ads have been served for this URL since it was last analyzed"
        ),
    )

    embedding = VectorField(dimensions=384, default=None, null=True, blank=True)

    history = HistoricalRecords()

    def __str__(self):
        """Simple override."""
        return f"{self.keywords} on {self.url}"

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        unique_together = ("url", "publisher")
