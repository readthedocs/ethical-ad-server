"""
List all payouts.

Example::

    # List all active payouts
    ./manage.py payouts

    # List all active payouts and show the email
    ./manage.py payouts --email
"""
import datetime
import sys
from pprint import pprint

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.template import Context
from django.template import Template

from ...models import Publisher
from ...utils import generate_publisher_payout_data
from adserver.utils import generate_absolute_url

email_template = """
{% autoescape off %}
<p>
Thanks for being one of the first publishers on our EthicalAds network.
We aim to get payouts completed by the 15th of the month,
as noted in our <a href="https://www.ethicalads.io/publisher-policy/">Publisher Policy</a>.
If you haven't had a chance to look it over, please do,
as it sets expectations around ad placements and payments.
</p>

{% if ctr < .06 %}

<p>
We generally expect all our publishers to maintain a CTR (click though rate) around or above .1%.
Your CTR is currently {{ report.total.ctr|floatformat:3 }}%,
which is below our current minimum.
We're working on documenting some recommendations for improving CTR,
but for now the primary thing is making sure your ads are displayed in a prominent place on your site.
</p>

{% endif %}

<p>
We are now processing payments for <strong>{{ today|date:"F" }} {{ today|date:"Y" }}</strong>,
and you made a total of <strong>${{ report.total.revenue_share|floatformat:2 }}</strong> for ads displayed between <strong>{{ last_payout_date|date:"F j" }}-{{ last_day_last_month|date:"F j" }}</strong>.
You can find the full report for this billing cycle on our <a href="{{ report_url }}">revenue report</a>.
</p>

{% if first %}
<p>
We need a few pieces of information from you in order to process a payment:
</p>

<p>
<ul>
<li>The name of the person or organization that will be receiving the payment</li>
<li>The address, including country, for the person/organization</li>
<li>Fill out the payment information in the <a href="{{ settings_url }}">publisher settings</a></li>
</ul>
</p>

<p>
Once we have this information, we will process the payment.
These will show up in the <a href="{{ payouts_url }}">payouts dashboard</a>,
once they have been started.
</p>

{% else %}

<p>
Since we have already processed a payout for you,
we should have all the information needed to move ahead.
You can always update your payout settings in the <a href="{{ settings_url }}">publisher settings</a>.
Payouts will show up in the <a href="{{ payouts_url }}">payouts dashboard</a> for your records once processed.
</p>

{% endif %}

<p>
Thanks again for being part of the EthicalAds network,
and we look forward to many more months of payouts!
</p>

<p>
Cheers,<br>
Eric
</p>
{% endautoescape %}
"""


class Command(BaseCommand):

    """Add a publisher from the command line."""

    def add_arguments(self, parser):
        parser.add_argument(
            "-e", "--email", help="Generate email", required=False, action="store_true"
        )
        parser.add_argument(
            "-s", "--send", help="Send email", required=False, action="store_true"
        )
        parser.add_argument(
            "-p", "--payout", help="Create payouts", required=False, action="store_true"
        )
        parser.add_argument(
            "--publisher", help="Specify a specific publisher", required=False
        )
        parser.add_argument(
            "-a",
            "--all",
            help="Output payouts for all publishers",
            required=False,
            action="store_true",
        )

    def handle(self, *args, **kwargs):
        print_email = kwargs.get("email")
        send_email = kwargs.get("send")
        create_payout = kwargs.get("payout")
        all_publishers = kwargs.get("all")
        publisher_slug = kwargs.get("publisher")

        self.stdout.write("Processing payouts. \n")

        queryset = Publisher.objects.all()
        if publisher_slug:
            queryset = queryset.filter(slug__contains=publisher_slug)

        for publisher in queryset:
            data = generate_publisher_payout_data(publisher)
            report = data.get("due_report")
            report_url = data.get("due_report_url")
            if not report:
                if not all_publishers:
                    print(f"Skipping for no due report: {publisher.slug}")
                    # Skip publishers without due money
                    continue
                report = data.get("current_report")
                report_url = data.get("current_report_url")

            due_balance = report["total"]["revenue_share"]
            due_str = "{:.2f}".format(due_balance)
            ctr = report["total"]["ctr"]

            if due_balance < float(50):
                print(f"Skipping for low balance: {publisher.slug} owed {due_str}")
                continue

            self.stdout.write("\n\n###########\n")
            self.stdout.write(str(publisher) + "\n")
            self.stdout.write(
                "total={:.2f}".format(due_balance)
                + " ctr={:.3f}".format(ctr)
                + " first={}".format(data.get("first"))
                + "\n"
            )
            self.stdout.write(report_url + "\n")
            self.stdout.write("###########\n\n")

            if print_email or send_email:
                payouts_url = generate_absolute_url(
                    "publisher_payouts", kwargs={"publisher_slug": publisher.slug}
                )
                settings_url = generate_absolute_url(
                    "publisher_settings", kwargs={"publisher_slug": publisher.slug}
                )
                context = dict(
                    report=report,
                    report_url=report_url,
                    payouts_url=payouts_url,
                    settings_url=settings_url,
                    publisher=publisher,
                    **data,
                )
                if ctr < 0.08:
                    print("Include CTR callout?")
                    ctr_proceed = input("y/n?: ")
                    if ctr_proceed:
                        context["ctr"] = ctr

                email_html = (
                    Template(email_template)
                    .render(Context(context))
                    .replace("\n\n", "\n")
                )

            if print_email:
                print(email_html)

            if send_email:
                token = getattr(settings, "FRONT_TOKEN")
                channel = getattr(settings, "FRONT_CHANNEL")
                author = getattr(settings, "FRONT_AUTHOR")

                if not token or not channel:
                    print("No front token, not sending email")
                    sys.exit()

                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }

                payload = {
                    # "to": ['eric@ericholscher.com'], # For testing
                    "to": [user.email for user in publisher.user_set.all()],
                    "sender_name": "EthicalAds by Read the Docs",
                    "subject": f"EthicalAds Payout - {publisher.name}",
                    "options": {"archive": False},
                    "body": email_html,
                }
                if author:
                    payload["author_id"] = author

                url = f"https://api2.frontapp.com/channels/{channel}/messages"

                print("Send email?")
                print(f"{payload['to']}: {payload['subject']}")
                proceed = input("y/n?: ")
                if not proceed == "y":
                    print("Skipping email.")
                else:
                    requests.request("POST", url, json=payload, headers=headers)
                    # pprint(response.json())

            if create_payout:
                print("Create Payout?")

                if publisher.payout_method:
                    if publisher.stripe_connected_account_id:
                        print(
                            f"Stripe: https://dashboard.stripe.com/connect/accounts/{publisher.stripe_connected_account_id}"
                        )
                    if publisher.open_collective_name:
                        print(
                            f"Open Collective: https://opencollective.com/{publisher.open_collective_name}"
                        )
                    if publisher.paypal_email:
                        print(f"Paypal: {publisher.paypal_email}")
                    print(due_str)
                    print(f"EthicalAds Payout - {publisher.name}")

                payout_proceed = input("y/n?: ")
                if not payout_proceed == "y":
                    print("Skipping payout")
                else:
                    publisher.payouts.create(
                        date=datetime.datetime.utcnow(),
                        method=publisher.payout_method,
                        amount=due_balance,
                        note=report_url,
                    )
