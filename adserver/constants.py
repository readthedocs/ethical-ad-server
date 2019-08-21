"""Contants used for the ad server."""
from django.utils.translation import ugettext as _


OFFERS = "offers"
VIEWS = "views"
CLICKS = "clicks"

IMPRESSION_TYPES = (OFFERS, VIEWS, CLICKS)

PAID_CAMPAIGN = "paid"
COMMUNITY_CAMPAIGN = "community"
HOUSE_CAMPAIGN = "house"
ALL_CAMPAIGN_TYPES = [PAID_CAMPAIGN, COMMUNITY_CAMPAIGN, HOUSE_CAMPAIGN]
CAMPAIGN_TYPES = (
    (PAID_CAMPAIGN, _("Paid")),
    (COMMUNITY_CAMPAIGN, _("Community")),
    (HOUSE_CAMPAIGN, _("House")),
)
