"""De-serializers for the ad server APIs"""
from rest_framework import serializers


class AdPlacementSerializer(serializers.Serializer):

    """
    De-serializes incoming possible ad placements for the API

    For example, a client may suggest 3 possible placements
    and have different <div> IDs for those and have different
    priorities for them.
    """

    div_id = serializers.CharField()
    ad_type = serializers.CharField(required=True)
    priority = serializers.IntegerField(
        default=1, min_value=1, max_value=10, required=False
    )


class AdDecisionSerializer(serializers.Serializer):

    """De-serializes incoming possibilities for the ad API"""

    placements = AdPlacementSerializer(many=True)

    # Whether this request should not show paid ads
    community_house = serializers.BooleanField(default=False, required=False)

    # Used to specify a specific ad or campaign to show (used for debugging mostly)
    force_ad = serializers.CharField(required=False)  # slug
    force_campaign = serializers.CharField(required=False)  # slug

    def validate_placements(self, placements):
        if not placements:
            raise serializers.ValidationError("At least one placement is required")

        return placements
