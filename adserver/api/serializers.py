"""De-serializers for the ad server APIs."""

import logging

import bleach
from django.core.exceptions import ValidationError
from django.core.files.images import get_image_dimensions
from django.core.validators import URLValidator
from django.core.validators import validate_ipv46_address
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from ..constants import ALL_CAMPAIGN_TYPES
from ..forms import AdvertisementFormMixin
from ..models import AdType
from ..models import Advertisement
from ..models import Advertiser
from ..models import Campaign
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

    def validate_ad_type(self, ad_type):
        """This ad type was renamed but the previous name was retained for backwards compatibility."""
        if ad_type == "text-only-large-v1":
            ad_type = "logo-large-v1"

        return ad_type


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
    placement_index = serializers.IntegerField(
        required=False, min_value=0, max_value=999
    )

    # Field sent when an ad is rotated but not sent when an ad is first loaded
    rotations = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=9,
    )

    # Used to pass the actual ad viewer's data for targeting purposes
    # The IP field purposefully isn't an IPAddressField so we can handle some invalid values
    # instead of rejecting them outright
    user_ip = serializers.CharField(required=False)
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
        # API users may send more than this, but keywords beyond this are ignored
        MAX_KEYWORDS = 20

        if keywords:
            # Lowercase all the keywords and strip surrounding whitespace.
            # Also, only take the first 20.
            keywords = [k.lower().strip() for k in keywords if k.strip()][:MAX_KEYWORDS]

        return keywords

    def validate_url(self, url):
        validator = URLValidator()
        try:
            validator(url)  # Throws ValidationError on invalid
            return url
        except ValidationError:
            raise serializers.ValidationError("Invalid ad referring URL")

    def validate_user_ip(self, ip):
        if ip and "," in ip:
            # If there are multiple IPs, take the first one
            # The client has probably sent the X-Forwarded-For header
            # https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/X-Forwarded-For
            ip = ip.split(",")[0].strip()

        # Perform basic validation of the IP address (after splitting if necessary)
        try:
            validate_ipv46_address(ip)
        except ValidationError:
            log.warning("Invalid ad decision user IP address: %s", ip)
            raise serializers.ValidationError("Invalid IPv4 or IPv6 address")

        return ip


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


class FlightManagementSerializer(serializers.ModelSerializer):
    """
    Serializes flights for the flight management API.

    Fields such as the price (CPC/CPM), the sold clicks or impressions,
    and the targeting can only be changed by users
    with the same Django permissions used by the flight management UI.
    """

    url = serializers.HyperlinkedIdentityField(
        view_name="api:flights-detail", lookup_field="slug"
    )
    campaign = serializers.SlugRelatedField(
        slug_field="slug", queryset=Campaign.objects.all()
    )
    advertiser = serializers.SlugField(
        source="campaign.advertiser.slug", read_only=True
    )
    state = serializers.CharField(read_only=True)

    class Meta:
        model = Flight
        fields = (
            "url",
            "name",
            "slug",
            "campaign",
            "advertiser",
            "state",
            "live",
            "hard_stop",
            "auto_renew",
            "start_date",
            "end_date",
            "cpc",
            "sold_clicks",
            "cpm",
            "sold_impressions",
            "daily_cap",
            "priority_multiplier",
            "pacing_interval",
            "prioritize_ads_ctr",
            "targeting_parameters",
            "total_views",
            "total_clicks",
            "created",
            "modified",
        )
        read_only_fields = (
            "slug",
            "total_views",
            "total_clicks",
            "created",
            "modified",
        )

    def __init__(self, *args, **kwargs):
        """Limit writable campaigns to ones the user has access to."""
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        if request and request.user.is_authenticated and not request.user.is_staff:
            self.fields["campaign"].queryset = Campaign.objects.filter(
                advertiser__in=request.user.advertisers.all()
            )

    def validate_campaign(self, campaign):
        if self.instance and campaign != self.instance.campaign:
            raise serializers.ValidationError(
                _("A flight cannot be moved to a different campaign")
            )
        return campaign

    def validate(self, data):
        """Mirror the validation from the flight management UI forms."""
        cpc = data.get("cpc", self.instance.cpc if self.instance else 0) or 0
        cpm = data.get("cpm", self.instance.cpm if self.instance else 0) or 0
        if cpc > 0 and cpm > 0:
            raise serializers.ValidationError(_("A flight cannot have both CPC & CPM"))

        start_date = data.get(
            "start_date", self.instance.start_date if self.instance else None
        )
        end_date = data.get(
            "end_date", self.instance.end_date if self.instance else None
        )
        if start_date and end_date and start_date >= end_date:
            raise serializers.ValidationError(
                _("The end date must come after the start date")
            )

        return data

    def generate_slug(self, name, campaign):
        """Generates an available flight slug the same way the flight create form does."""
        campaign_slug = campaign.slug
        slug = slugify(name)
        if not slug.startswith(campaign_slug):
            slug = slugify(f"{campaign_slug}-{slug}")

        while Flight.objects.filter(slug=slug).exists():
            random_char = get_random_string(1)
            slug = slugify(f"{slug}-{random_char}")

        return slug

    def create(self, validated_data):
        validated_data["slug"] = self.generate_slug(
            validated_data["name"], validated_data["campaign"]
        )
        return super().create(validated_data)


class AdvertisementManagementSerializer(serializers.ModelSerializer):
    """
    Serializes advertisements for the ad management API.

    New ads must use the ``headline``, ``content``, and ``cta`` fields.
    The ``text`` field is read-only and only set on old ads.
    """

    url = serializers.HyperlinkedIdentityField(
        view_name="api:advertisements-detail", lookup_field="slug"
    )
    flight = serializers.SlugRelatedField(
        slug_field="slug", queryset=Flight.objects.all()
    )
    advertiser = serializers.SlugField(
        source="flight.campaign.advertiser.slug", read_only=True
    )
    ad_types = serializers.SlugRelatedField(
        slug_field="slug", many=True, queryset=AdType.objects.all()
    )

    class Meta:
        model = Advertisement
        fields = (
            "url",
            "name",
            "slug",
            "flight",
            "advertiser",
            "live",
            "ad_types",
            "image",
            "link",
            "text",
            "headline",
            "content",
            "cta",
            "created",
            "modified",
        )
        read_only_fields = ("slug", "text", "created", "modified")

    def __init__(self, *args, **kwargs):
        """Limit writable flights to ones the user has access to."""
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        if request and request.user.is_authenticated and not request.user.is_staff:
            self.fields["flight"].queryset = Flight.objects.filter(
                campaign__advertiser__in=request.user.advertisers.all()
            )

    def validate_flight(self, flight):
        if self.instance and flight != self.instance.flight:
            raise serializers.ValidationError(
                _("An advertisement cannot be moved to a different flight")
            )
        return flight

    def validate(self, data):
        """Mirror the validation from the advertisement management UI forms."""
        instance = self.instance
        messages = AdvertisementFormMixin.messages

        flight = data.get("flight") or (instance.flight if instance else None)

        if "ad_types" in data:
            ad_types = data["ad_types"]
        elif instance:
            ad_types = list(instance.ad_types.all())
        else:
            ad_types = []

        if "image" in data:
            image = data["image"]
        elif instance:
            image = instance.image
        else:
            image = None

        headline = data.get("headline", instance.headline if instance else None) or ""
        content = data.get("content", instance.content if instance else None)
        cta = data.get("cta", instance.cta if instance else None) or ""

        if not ad_types:
            raise serializers.ValidationError(
                {"ad_types": messages["ad_type_required"]}
            )

        # Ad types must be valid for the campaign's publisher groups
        # and deprecated ad types are only allowed if the ad already has them
        allowed_ad_type_pks = set(
            flight.campaign.allowed_ad_types().values_list("pk", flat=True)
        )
        current_ad_type_pks = set()
        if instance:
            current_ad_type_pks = {at.pk for at in instance.ad_types.all()}
        for ad_type in ad_types:
            if ad_type.pk not in allowed_ad_type_pks or (
                ad_type.deprecated and ad_type.pk not in current_ad_type_pks
            ):
                raise serializers.ValidationError(
                    {
                        "ad_types": _(
                            "'%(ad_type)s' is not a valid ad type for this flight"
                        )
                        % {"ad_type": ad_type.slug}
                    }
                )

        # New ads and ads already converted to the new style
        # require the ad content (the text field is read-only)
        if not content:
            if not (instance and instance.text and not instance.content):
                raise serializers.ValidationError(
                    {"content": _("This field is required.")}
                )
            stripped_text = bleach.clean(instance.text, tags=[], strip=True)
        else:
            stripped_text = f"{headline}{content}{cta}"

        errors = {}
        for ad_type in ad_types:
            # If any of the chosen ad types require images,
            # fail validation if there is no image
            if ad_type.has_image and not image:
                errors.setdefault("image", []).append(
                    messages["missing_image"] % {"ad_type": ad_type}
                )

            if ad_type.has_image and image and not ad_type.validate_image(image):
                width, height = get_image_dimensions(image)
                errors.setdefault("image", []).append(
                    messages["invalid_dimensions"]
                    % {
                        "ad_type": ad_type,
                        "ad_type_width": ad_type.image_width,
                        "ad_type_height": ad_type.image_height,
                        "width": width,
                        "height": height,
                    }
                )

            # Check text length
            if ad_type.max_text_length and not ad_type.validate_text(stripped_text):
                errors.setdefault("content", []).append(
                    messages["text_too_long"]
                    % {
                        "ad_type": ad_type,
                        "ad_type_max_chars": ad_type.max_text_length,
                        "text_len": len(stripped_text),
                    }
                )

        if errors:
            raise serializers.ValidationError(errors)

        return data

    def create(self, validated_data):
        validated_data["slug"] = Advertisement.generate_slug(validated_data["name"])
        return super().create(validated_data)
