"""Handle specific Stripe webhooks with special logic."""
import logging

import stripe
from django_slack import slack_message
from djstripe import webhooks
from djstripe.models import Invoice


log = logging.getLogger(__name__)  # noqa


@webhooks.handler("invoice.payment_succeeded")
def invoice_paid_to_slack(event, **kwargs):
    """Post paid invoices to Slack."""
    data = event.data["object"]

    # This is a little over-engineered
    # However, by fetching from Stripe and then syncing,
    # we ensure there isn't a race condition between the webhook and this handler
    # Also, this will work in test-mode as well as production
    invoice_id = data["id"]
    invoice = Invoice.sync_from_stripe_data(stripe.Invoice.retrieve(invoice_id))

    log.debug("Stripe invoice %s is paid. Posting to Slack...", invoice)
    slack_message(
        "adserver/slack/invoice-paid.slack",
        {
            "customer": invoice.customer,
            "invoice": invoice,
        },
    )
