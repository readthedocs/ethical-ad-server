"""Management command to refresh denormalized total_views and total_clicks on Flight objects."""

import logging

from django.core.management.base import BaseCommand

from ...models import Flight


log = logging.getLogger(__name__)


class Command(BaseCommand):
    """Refresh denormalized total_views and total_clicks for flights."""

    help = "Refresh denormalized total_views and total_clicks fields for all flights"

    def add_arguments(self, parser):
        parser.add_argument(
            "--live-only",
            action="store_true",
            help="Only refresh live flights",
        )
        parser.add_argument(
            "--flight-slug",
            type=str,
            help="Refresh only a specific flight by slug",
        )

    def handle(self, *args, **options):
        live_only = options.get("live_only", False)
        flight_slug = options.get("flight_slug")

        if flight_slug:
            flights = Flight.objects.filter(slug=flight_slug)
            if not flights.exists():
                self.stderr.write(self.style.ERROR(f"Flight '{flight_slug}' not found"))
                return
        elif live_only:
            flights = Flight.objects.filter(live=True)
        else:
            flights = Flight.objects.all()

        count = flights.count()
        self.stdout.write(f"Refreshing denormalized totals for {count} flight(s)...")

        for i, flight in enumerate(flights.iterator(), 1):
            try:
                flight.refresh_denormalized_totals()
                if i % 100 == 0:
                    self.stdout.write(f"  Processed {i}/{count} flights...")
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(f"Failed to refresh flight '{flight.slug}': {e}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully refreshed denormalized totals for {count} flight(s)"
            )
        )
