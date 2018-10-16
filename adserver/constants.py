"""Contants used for the ad server"""

from django.utils.translation import ugettext as _


PAID_CAMPAIGN = "paid"
COMMUNITY_CAMPAIGN = "community"
HOUSE_CAMPAIGN = "house"
CAMPAIGN_TYPES = (
    (PAID_CAMPAIGN, _("Paid")),
    (COMMUNITY_CAMPAIGN, _("Community")),
    (HOUSE_CAMPAIGN, _("House")),
)
