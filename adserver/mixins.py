"""Mixins for advertiser and publisher views."""
from django.shortcuts import get_object_or_404

from .models import Advertiser
from .models import Publisher


class AdvertiserAccessMixin:

    """Mixin for checking advertiser access that works with the ``UserPassesTestMixin``."""

    advertiser_slug_parameter = "advertiser_slug"

    def test_func(self):
        """The user must have access on the advertiser or be staff."""
        if self.request.user.is_anonymous:
            return False

        advertiser = get_object_or_404(
            Advertiser, slug=self.kwargs[self.advertiser_slug_parameter]
        )
        return (
            self.request.user.is_staff
            or advertiser in self.request.user.advertisers.all()
        )


class PublisherAccessMixin:

    """Mixin for checking publisher access that works with the ``UserPassesTestMixin``."""

    publisher_slug_parameter = "publisher_slug"

    def test_func(self):
        """The user must have access on the publisher or be staff."""
        if self.request.user.is_anonymous:
            return False

        publisher = get_object_or_404(
            Publisher, slug=self.kwargs[self.publisher_slug_parameter]
        )
        return (
            self.request.user.is_staff
            or publisher in self.request.user.publishers.all()
        )
