"""
Custom permissions for our API.

https://www.django-rest-framework.org/api-guide/permissions/#custom-permissions
"""

from rest_framework import permissions

from ..models import Advertisement
from ..models import Advertiser
from ..models import Flight
from ..models import Publisher


class AdvertiserPermission(permissions.IsAuthenticated):
    """
    Checks whether the authenticated user is associated with the given advertiser.

    For staff users, this will always return True
    For unauthenticated users, this is always False
    """

    def has_object_permission(self, request, view, obj):
        if not isinstance(obj, Advertiser) or request.user.is_anonymous:
            return False

        advertiser = obj
        return (
            request.user.is_staff
            or request.user.advertisers.filter(id=advertiser.id).exists()
        )


class PublisherPermission(permissions.IsAuthenticated):
    """
    Checks whether the authenticated user is associated with the given publisher.

    For staff users, this will always return True
    For unauthenticated users, this is always False
    """

    def has_object_permission(self, request, view, obj):
        if not isinstance(obj, Publisher) or request.user.is_anonymous:
            return False

        publisher = obj
        return (
            request.user.is_staff
            or request.user.publishers.filter(id=publisher.id).exists()
        )


class FlightPermission(permissions.DjangoModelPermissions):
    """
    Checks whether the user can view or manage a flight.

    Viewing a flight requires an authenticated user with any role
    on the flight's advertiser (staff can view all flights).
    Creating and updating flights additionally requires
    the same Django model permissions used by the flight management UI
    (``adserver.add_flight`` and ``adserver.change_flight`` respectively).
    """

    def has_object_permission(self, request, view, obj):
        if not isinstance(obj, Flight) or request.user.is_anonymous:
            return False

        advertiser = obj.campaign.advertiser
        return request.user.is_staff or request.user.has_advertiser_permission(
            advertiser
        )


class AdvertisementPermission(permissions.IsAuthenticated):
    """
    Checks whether the user can view or manage an advertisement.

    Viewing an ad requires an authenticated user with any role
    on the ad's advertiser.
    Creating, updating, and removing ads requires a manager or admin role
    on the advertiser.
    Staff users can always view and manage ads.
    """

    def has_object_permission(self, request, view, obj):
        if not isinstance(obj, Advertisement) or request.user.is_anonymous:
            return False

        if request.user.is_staff:
            return True

        advertiser = obj.flight.campaign.advertiser
        if request.method in permissions.SAFE_METHODS:
            return request.user.has_advertiser_permission(advertiser)

        return request.user.has_advertiser_manager_permission(advertiser)


class AdDecisionPermission(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if not isinstance(obj, Publisher):
            return False

        publisher = obj
        return (
            publisher.unauthed_ad_decisions
            or request.user.is_staff
            or (
                not request.user.is_anonymous
                and request.user.publishers.filter(id=publisher.id).exists()
            )
        )
