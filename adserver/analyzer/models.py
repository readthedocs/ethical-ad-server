"""Stored results of offline content targeting analysis."""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django_extensions.db.models import TimeStampedModel

from ..models import Advertiser
from ..models import Flight
from ..models import Publisher
from ..utils import get_domain_from_url
from .utils import normalize_url
from .validators import KeywordsValidator


class BaseAnalyzedUrl(TimeStampedModel):
    url = models.URLField(
        db_index=True,
        max_length=1024,
        help_text=_(
            "URL of the page being analyzed after certain query parameters are stripped away"
        ),
    )
    domain = models.CharField(
        _("Domain"),
        db_index=True,
        max_length=1024,
        null=True,
        blank=True,
        default=None,
    )

    # Fields below are updated by the analyzer
    keywords = models.JSONField(
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

    title = models.TextField(
        _("Title of the page"),
        default=None,
        null=True,
        blank=True,
    )

    description = models.TextField(
        _("Description of the page"),
        default=None,
        null=True,
        blank=True,
    )

    def __str__(self):
        """Simple override."""
        return self.url

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        abstract = True


class AnalyzedUrl(BaseAnalyzedUrl):
    """Analyzed keywords for a given URL."""

    publisher = models.ForeignKey(
        Publisher,
        help_text=_("Publisher where this URL appears"),
        on_delete=models.CASCADE,
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

    class Meta:
        unique_together = ("url", "publisher")


class AnalyzedAdvertiserUrl(BaseAnalyzedUrl):
    """Analyzed keywords for a given URL."""

    advertiser = models.ForeignKey(
        Advertiser,
        help_text=_("Advertiser with the URL"),
        on_delete=models.CASCADE,
    )

    flights = models.ManyToManyField(
        Flight,
        help_text=_("Flights to filter this URL by"),
        blank=True,
    )

    class Meta:
        unique_together = ("url", "advertiser")

    @classmethod
    def set_urls_on_flight(cls, flight, urls):
        """
        Set the URLs for a flight.

        This will create new AnalyzedAdvertiserUrl objects if applicable for each URL
        and associate them with the flight.
        Any URLs that are no longer associated with the flight will be removed.
        """
        urls = [normalize_url(url) for url in urls]

        # Remove any URLs that are no longer associated with the flight
        for analyzed_url in cls.objects.filter(
            advertiser=flight.campaign.advertiser,
        ).exclude(url__in=urls):
            analyzed_url.flights.remove(flight)

        for url in urls:
            domain = get_domain_from_url(url)
            analyzed_url, _ = cls.objects.get_or_create(
                url=url,
                advertiser=flight.campaign.advertiser,
                defaults={
                    "domain": domain,
                },
            )
            analyzed_url.flights.add(flight)
