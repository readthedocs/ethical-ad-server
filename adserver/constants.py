"""Contants used for the ad server."""
from django.utils.translation import ugettext as _


DECISIONS = "decisions"
OFFERS = "offers"
VIEWS = "views"
CLICKS = "clicks"

IMPRESSION_TYPES = (DECISIONS, OFFERS, VIEWS, CLICKS)

PAID_CAMPAIGN = "paid"
AFFILIATE_CAMPAIGN = "affiliate"
COMMUNITY_CAMPAIGN = "community"
HOUSE_CAMPAIGN = "house"
ALL_CAMPAIGN_TYPES = [
    PAID_CAMPAIGN,
    AFFILIATE_CAMPAIGN,
    COMMUNITY_CAMPAIGN,
    HOUSE_CAMPAIGN,
]
CAMPAIGN_TYPES = (
    (PAID_CAMPAIGN, _("Paid")),
    (AFFILIATE_CAMPAIGN, _("Affiliate")),
    (COMMUNITY_CAMPAIGN, _("Community")),
    (HOUSE_CAMPAIGN, _("House")),
)

PAYOUT_STRIPE = "stripe"
PAYOUT_PAYPAL = "paypal"
PAYOUT_OPENCOLLECTIVE = "opencollective"
PAYOUT_OTHER = "other"
PUBLISHER_PAYOUT_METHODS = (
    (PAYOUT_STRIPE, _("Stripe (Bank transfer, debit card)")),
    (PAYOUT_PAYPAL, _("PayPal")),
    (PAYOUT_OPENCOLLECTIVE, _("Open Collective")),
    (PAYOUT_OTHER, _("Other")),
)
