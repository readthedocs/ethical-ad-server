"""De-serializers for the ad server APIs."""
import logging

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from ..constants import ALL_CAMPAIGN_TYPES
from ..models import Advertisement
from ..models import Advertiser
from ..models import Flight
from ..models import Publisher


log = logging.getLogger(__name__)  # noqa


class AdPlacementSerializer(serializers.Serializer):

    """
    De-serializes incoming possible ad placements for the API.

    For example, a client may suggest 3 possible placements
    and have different <div> IDs for those and have different
    priorities for them.
    """

    div_id = serializers.CharField()
    ad_type = serializers.CharField(required=True)
    priority = serializers.IntegerField(
        default=1,
        min_value=1,
        max_value=10,
        required=False,
        help_text=_(
            "The lowest priority placement should be 1 (the default) while the highest possible priority is 10."
        ),
    )


class AdDecisionSerializer(serializers.Serializer):

    """De-serializes incoming possibilities for the ad API."""

    # Required fields
    placements = AdPlacementSerializer(many=True)
    publisher = serializers.SlugField(required=True)

    keywords = serializers.ListField(
        child=serializers.CharField(allow_blank=True), max_length=100, required=False
    )

    # Whether this request should only consider a certain kind of ad
    campaign_types = serializers.ListField(
        child=serializers.CharField(), max_length=10, required=False
    )

    # The URL where the ad will appear
    # This purposefully doesn't use a URLField so we can disregard invalid values rather than rejecting them
    url = serializers.CharField(max_length=256, required=False)

    # The placement index (0-indexed)
    # 1 or more means there's multiple placements on this page
    placement_index = serializers.IntegerField(required=False, min_value=0, max_value=9)

    # Used to pass the actual ad viewer's data for targeting purposes
    user_ip = serializers.IPAddressField(required=False)
    user_ua = serializers.CharField(required=False)

    # Used to specify a specific ad or campaign to show (used for debugging mostly)
    force_ad = serializers.CharField(required=False)  # slug
    force_campaign = serializers.CharField(required=False)  # slug

    def validate_placements(self, placements):
        if not placements:
            raise serializers.ValidationError("At least one placement is required")

        return placements

    def validate_campaign_types(self, campaign_types):
        if campaign_types:
            for campaign_type in campaign_types:
                if campaign_type not in ALL_CAMPAIGN_TYPES:
                    raise serializers.ValidationError("Invalid campaign type")

        return campaign_types

    def validate_publisher(self, publisher_slug):
        # Resolve the publisher slug into the actual Publisher
        publisher = Publisher.objects.filter(slug=publisher_slug).first()
        if not publisher:
            raise serializers.ValidationError("Invalid publisher")
        if publisher.disabled:
            raise serializers.ValidationError("Disabled publisher")

        return publisher

    def validate_keywords(self, keywords):
        if keywords:
            # Lowercase all the keywords and strip surrounding whitespace
            keywords = [k.lower().strip() for k in keywords if k.strip()]

        return keywords

    def validate_url(self, url):
        validator = URLValidator()
        try:
            validator(url)  # Throws ValidationError on invalid
            return url
        except ValidationError:
            log.warning("Invalid ad decision referring URL: %s", url)
            return None


class PublisherSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Publisher
        fields = ("url", "name", "slug", "created", "modified")
        extra_kwargs = {
            "url": {"view_name": "api:publishers-detail", "lookup_field": "slug"}
        }


class AdvertiserSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Advertiser
        fields = ("url", "name", "slug", "created", "modified")
        extra_kwargs = {
            "url": {"view_name": "api:advertisers-detail", "lookup_field": "slug"}
        }


class FlightSerializer(serializers.ModelSerializer):
    targeting_parameters = serializers.SerializerMethodField()

    class Meta:
        model = Flight
        fields = (
            "name",
            "slug",
            "live",
            "cpc",
            "cpm",
            "targeting_parameters",
            "start_date",
            "end_date",
            "created",
            "modified",
        )

    def get_targeting_parameters(self, obj):
        return obj.targeting_parameters


class AdvertisementSerializer(serializers.ModelSerializer):
    ad_types = serializers.SerializerMethodField()

    class Meta:
        model = Advertisement
        fields = (
            "name",
            "slug",
            "text",
            "image",
            "link",
            "ad_types",
            "live",
            "created",
            "modified",
        )

    def get_ad_types(self, obj):
        return [t.name for t in obj.ad_types.all()]
