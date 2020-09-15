"""
List all payouts.

Example::

   ./manage.py payouts
"""
import re
from datetime import datetime
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.template import Context
from django.template import Template
from django.urls import reverse
from django.utils.text import slugify

from ...models import Publisher
from ...models import PublisherGroup
from ...models import PublisherPayout
from adserver.auth.models import User
from adserver.utils import generate_absolute_url

email_template = re.sub(
    r"\n\n",
    r"\n",
    """

Thanks for being one of the first publishers on our EthicalAds network.
We aim to get payouts completed by the 15th of the month,
as noted in our [Publisher Policy](https://www.ethicalads.io/publisher-policy/).
If you haven't had a chance to look it over, please do,
as it sets expectations around ad placements and payments.

{% if ctr < .07 %}

As noted in our Publisher policy,
we expect all our publishers to maintain a CTR (click though rate) around or above .1%.
Your CTR is currently {{ ctr|floatformat:3 }}%,
which is below our current minimum.
We're working on documenting some recommendations for improving CTR,
but for now the primary thing is making sure your ads are displayed in a prominent place.

{% endif %}

We are now processing payments for **{{ month }} {{ year }}**,
and you made a total of **{{ total }}**.
You can find the full report for this billing cycle on our [dashboard]({{ report_url }}).

{% if first %}
We need a few pieces of information from you in order to process a payment:

* The name of the person or organization that will be receiving the payment
* The address, including country, for the person/organization
* Fill out the payment information in the [Publisher settings]({{ settings_url }})

Once we have this information, we will process our initial payouts.
These will show up in the [Payouts dashboard]({{ payouts_url }}), once they have been started.

{% else %}

Since we have already processed a payout for you,
we should have all the information needed to move ahead.
You can always update your payout settings in the [Publisher settings]({{ settings_url }}).

{% endif %}

Thanks again for being part of the EthicalAds network,
and we look forward to many more months of payouts!

Cheers,
Eric

""",
)


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
            # user = publisher.user_set.first()
            last_payout = publisher.payouts.last()
            first = False

            if not last_payout:
                first = True
                # Fake a payout from 2020-01-01 to make the logic work.
                fake_date = datetime(year=2020, month=1, day=1)
                last_payout = PublisherPayout(date=fake_date, amount=0)

            report = publisher.daily_reports(
                start_date=last_payout.date.replace(day=1), end_date=month
            )
            due_balance = report["total"]["revenue_share"]
            ctr = report["total"]["ctr"]
            due_str = "{:.2f}".format(due_balance)
            if due_balance > float(50):
                report_url = (
                    generate_absolute_url(
                        "publisher_report", kwargs={"publisher_slug": publisher.slug}
                    )
                    + "?start_date="
                    + last_payout.date.strftime("%Y-%m-01")
                    + "&end_date="
                    + month.strftime("%Y-%m-%d")
                )
                print(publisher, due_str)
                print("CTR {:.3f}".format(ctr))
                print("https://server.ethicalads.io" + report_url)
                print(
                    Template(email_template).render(
                        Context(
                            dict(
                                first=first,
                                ctr=ctr,
                                month=month.strftime("%B"),
                                year=month.strftime("%Y"),
                                total=due_str,
                                report_url=report_url,
                                payouts_url=generate_absolute_url(
                                    "publisher_payouts",
                                    kwargs={"publisher_slug": publisher.slug},
                                ),
                                settings_url=generate_absolute_url(
                                    "publisher_settings",
                                    kwargs={"publisher_slug": publisher.slug},
                                ),
                            )
                        )
                    )
                )
