"""
Custom permissions for our API.

https://www.django-rest-framework.org/api-guide/permissions/#custom-permissions
"""

from rest_framework import permissions

from ..models import Advertiser
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
