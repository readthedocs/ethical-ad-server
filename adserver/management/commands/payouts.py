"""
List all payouts.

Example::

   ./manage.py payouts
"""
from datetime import datetime
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils.text import slugify

from ...models import Publisher
from ...models import PublisherGroup
from ...models import PublisherPayout
from adserver.auth.models import User

EMAIL = """

Thanks for being one of the first publishers on our EthicalAds network.
We aim to get payouts completed by the 15th of the month,
as noted in our [Publisher Policy](https://www.ethicalads.io/publisher-policy/).
If you haven't had a chance to look it over, please do,
as it sets expectations around ad placements and payments.

We are now processing payments for **{month} {year}**,
and you made a total of **{total}**.
You can find the full report for this billing cycle on our [dashboard]({report_url}).

We need a few pieces of information from you in order to process a payment:

* The name of the person or organization that will be receiving the payment
* The address, including country, for the person/organization
* Detailed payment information for your payment method of choice. We currently support OpenCollective, PayPal, Wire transfers, and ACH (US-only).

Once we have this information, we will process our initial payouts. These will show up in the [Payouts dashboard]({payouts_url}), once they have been started.

Thanks again for being part of the EthicalAds network, and we look forward to many more months of payouts!

Cheers,
Eric

"""


class Command(BaseCommand):

    """Add a publisher from the command line."""

    # def add_arguments(self, parser):
    #     parser.add_argument("-d", "--date", type=str, help="Date", required=True)
    #     parser.add_argument(
    #         "-g",
    #         "--group",
    #         type=str,
    #         help="Publisher group",
    #         default="ethicalads-network",
    #     )

    def handle(self, *args, **kwargs):
        today = datetime.utcnow()
        month = today.replace(day=1) - timedelta(days=1)
        for publisher in Publisher.objects.all():
            user = publisher.user_set.first()
            payouts = publisher.payouts.all()
            last_payout = payouts.last()
            first = False

            if not last_payout:
                first = True
                # Fake a payout from 2020-01-01 to make the logic work.
                fake_date = datetime(year=2020, month=1, day=1)
                last_payout = PublisherPayout(date=fake_date, amount=0)

            due_balance = publisher.total_revshare_sum(
                start_date=last_payout.date.replace(day=1), end_date=month
            )
            due_str = "{:.2f}".format(due_balance)
            if due_balance > float(50):
                report_url = (
                    reverse(
                        "publisher_report", kwargs={"publisher_slug": publisher.slug}
                    )
                    + "?start_date="
                    + last_payout.date.strftime("%Y-%m-01")
                    + "&end_date="
                    + month.strftime("%Y-%m-%d")
                )
                print(publisher, due_str)
                print("https://server.ethicalads.io" + report_url)
                # print(EMAIL.format(
                #     month=month.strftime("M"),
                #     year=month.strftime("Y"),
                #     total=due_str,
                #     report_url=report_url,
                #     payouts_url=reverse('publisher_payouts', kwargs={"publisher_slug": publisher.slug})
                # ))
