"""Views for the administrator actions."""

import datetime
import json
import logging

import requests
import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.template.loader import get_template
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView
from django.views.generic import FormView
from django.views.generic import TemplateView
from djstripe.models import Transfer

from adserver.utils import generate_publisher_payout_data

from ..constants import PAID
from ..constants import PAYOUT_PAYPAL
from ..constants import PAYOUT_STRIPE
from ..constants import PUBLISHER_PAYOUT_METHODS
from ..mixins import StaffUserMixin
from ..models import Advertiser
from ..models import Publisher
from .forms import CreateAdvertiserForm
from .forms import CreatePublisherForm
from .forms import StartPublisherPayoutForm


log = logging.getLogger(__name__)  # noqa


class CreateAdvertiserView(PermissionRequiredMixin, FormView):
    form_class = CreateAdvertiserForm
    model = Advertiser
    permission_required = "adserver.add_advertiser"
    template_name = "adserver/staff/advertiser-create.html"

    def form_valid(self, form):
        self.object = form.save()
        result = super().form_valid(form)
        messages.success(
            self.request,
            _("Successfully created %(advertiser)s") % {"advertiser": self.object.name},
        )
        return result

    def get_success_url(self):
        return reverse(
            "advertiser_main",
            kwargs={
                "advertiser_slug": self.object.slug,
            },
        )


class CreatePublisherView(PermissionRequiredMixin, FormView):
    form_class = CreatePublisherForm
    model = Publisher
    permission_required = "adserver.add_publisher"
    template_name = "adserver/staff/publisher-create.html"

    def form_valid(self, form):
        self.object = form.save()
        result = super().form_valid(form)
        messages.success(
            self.request,
            _("Successfully created %(object)s") % {"object": self.object.name},
        )
        return result

    def get_success_url(self):
        return reverse(
            "publisher_main",
            kwargs={
                "publisher_slug": self.object.slug,
            },
        )


class PublisherPayoutView(StaffUserMixin, TemplateView):
    """
    A view listing all the payouts that are due in the upcoming month.

    Has the following arguments:
    * first: Show only payouts for the first time
    * paid: Show only payouts that have already been paid
    * publisher: Filter to a specific publisher
    * payout_method: Filter to a specific payout method
    """

    template_name = "adserver/staff/publisher-payout-list.html"
    # Cache for 24 hours so we can finish payouts
    CACHE_SECONDS = 3600 * 24

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        publisher_slug = self.request.GET.get("publisher")
        first = self.request.GET.get("first", "")
        paid = self.request.GET.get("paid", "")
        payout_method = self.request.GET.get("payout_method", "")

        queryset = Publisher.objects.filter(skip_payouts=False)
        if publisher_slug:
            queryset = queryset.filter(slug__startswith=publisher_slug)
        if payout_method:
            queryset = queryset.filter(payout_method=payout_method)

        payouts = {}

        today = timezone.now()

        for publisher in queryset:
            current_payout = publisher.payouts.filter(
                date__month=today.month,
                date__year=today.year,
            ).first()

            # Cache payout data to make running payouts faster
            cache_key = f"payout-due-{today.year}-{today.month}-{publisher.pk}"
            data = cache.get(cache_key)
            if not data:
                data = generate_publisher_payout_data(
                    publisher, include_current_report=False
                )
                cache.set(cache_key, data, self.CACHE_SECONDS)

            report = data.get("due_report")

            if not report and not current_payout:
                continue

            if (paid == "True" and current_payout is None) or (
                paid == "False" and current_payout is not None
            ):
                # Filter by ``paid``, allowing for 3 states (''=all, False=not first, True=first)
                continue

            if (first == "True" and data["first"] is False) or (
                first == "False" and data["first"] is True
            ):
                # Filter by ``first``, allowing for 3 states (''=all, False=not first, True=first)
                continue

            if report:
                due_balance = report["total"]["revenue_share"]
                due_str = "{:.2f}".format(due_balance)
                ctr_str = "{:.2f}".format(report["total"]["ctr"])

            else:
                due_balance = current_payout.amount
                due_str = "{:.2f}".format(due_balance)
                ctr_str = "Unknown"

            if due_balance < float(settings.ADSERVER_MINIMUM_PAYOUT):
                # Skip publishers with low balance
                continue

            payout_context = dict(
                total=due_str,
                ctr=ctr_str,
                **data,
            )

            if current_payout:
                payout_context["payout"] = current_payout

            last_payout = publisher.payouts.filter(
                status=PAID,
                # Janky way to find last month..
                date__month=(
                    timezone.now().replace(day=1) - datetime.timedelta(days=1)
                ).month,
                date__year=timezone.now().year,
            ).first()
            if last_payout:
                change_percent = (
                    (float(due_balance) - float(last_payout.amount))
                    / float(last_payout.amount)
                ) * 100
                payout_context["change"] = change_percent

            payouts[publisher] = payout_context

        context["payouts"] = payouts
        # Filtering options
        context["first"] = first
        context["paid"] = paid
        context["publisher_slug"] = publisher_slug
        context["payout_method"] = payout_method
        context["boolean_options"] = [["", "---"], ["True", "True"], ["False", "False"]]
        context["payout_method_options"] = list(PUBLISHER_PAYOUT_METHODS)
        return context


class PublisherStartPayoutView(StaffUserMixin, FormView):
    """Start a payout for a publisher."""

    form_class = StartPublisherPayoutForm
    template_name = "adserver/staff/publisher-payout-start.html"

    def get_initial(self):
        """Returns the initial data to use for forms on this view."""
        initial = super().get_initial()
        publisher_slug = self.kwargs.get("publisher_slug")
        self.publisher = Publisher.objects.get(slug=publisher_slug)
        self.data = generate_publisher_payout_data(self.publisher)
        email_html = (
            get_template("adserver/email/publisher-payout.html")
            .render(self.data)
            .replace("\n\n", "\n")
        ).strip()
        initial["sender"] = "EthicalAds by Read the Docs"
        initial["subject"] = f"EthicalAds Payout - {self.publisher.name}"
        initial["body"] = email_html
        initial["amount"] = "%.2f" % self.get_amount(self.data["due_report"])
        initial["payout_method"] = self.publisher.get_payout_method_display()
        return initial

    def form_valid(self, form):
        self.object = form.save()
        result = super().form_valid(form)
        messages.success(
            self.request,
            _("Successfully emailed %(publisher)s")
            % {"publisher": self.publisher.name},
        )
        return result

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        publisher_slug = self.kwargs.get("publisher_slug")
        kwargs["publisher"] = Publisher.objects.get(slug=publisher_slug)
        kwargs["amount"] = "%.2f" % self.get_amount(self.data["due_report"])
        kwargs["start_date"] = self.data["start_date"]
        kwargs["end_date"] = self.data["end_date"]
        return kwargs

    def get_success_url(self):
        return reverse(
            "staff-finish-publisher-payout",
            kwargs={
                "publisher_slug": self.publisher.slug,
            },
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"publisher": self.publisher})
        return context

    def get_amount(self, due_report):
        if not due_report:
            return 0
        return due_report["total"]["revenue_share"]


class PublisherFinishPayoutView(StaffUserMixin, DetailView):
    """Start a payout for a publisher."""

    template_name = "adserver/staff/publisher-payout-finish.html"

    def get_object(self, queryset=None):
        self.publisher = get_object_or_404(
            Publisher, slug=self.kwargs["publisher_slug"]
        )
        # Get the last payout, which is the one we actually want to pay out,
        # since there could be multiple with status=EMAILED from previous months.
        self.payout = self.publisher.payouts.exclude(status=PAID).last()
        if not self.payout:
            raise Http404("No payout found")
        return self.payout

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"payout": self.payout, "publisher": self.publisher})
        return context

    def post(self, request, *args, **kwargs):
        self.get_object()

        # Automatically handle payout via Stripe
        if self.payout.method == PAYOUT_STRIPE and self.request.POST.get(
            "stripe-payout-confirm"
        ):
            transfer = self.pay_via_stripe_connect(self.payout)
            self.payout.note = f"Stripe Transfer: { transfer.id }"
            messages.success(self.request, _("Successfully paid via Stripe Connect"))
        elif self.payout.method == PAYOUT_PAYPAL and self.request.POST.get(
            "paypal-payout-confirm"
        ):
            transfer_id = self.pay_via_paypal(self.payout)
            self.payout.note = f"Paypal Transfer: { transfer_id }"
            messages.success(self.request, _("Successfully paid via PayPal"))

        self.payout.status = PAID
        self.payout.save()
        messages.success(self.request, _("Successfully updated payout to paid status"))
        return redirect(self.payout.get_absolute_url())

    def pay_via_stripe_connect(self, payout):
        """
        Perform a Stripe connected account transfer for this payout.

        See: https://docs.stripe.com/connect/separate-charges-and-transfers?platform=web&ui=stripe-hosted#create-transfer
        """
        publisher = payout.publisher
        amount = int(100 * payout.amount)  # Convert to US cents and make it an integer
        xfer = stripe.Transfer.create(
            amount=amount,
            currency="usd",
            destination=publisher.djstripe_account.id,
            transfer_group=f"PublisherPayout-{ self.payout.id }",
        )
        return Transfer.sync_from_stripe_data(xfer)

    def pay_via_paypal(self, payout):
        """
        Perform a PayPal payout.

        See: https://developer.paypal.com/docs/api/payments.payouts-batch/v1/
        """
        publisher = payout.publisher
        paypal_email = publisher.paypal_email
        amount = str(round(payout.amount, 2))  # PayPal wants the amount as a string

        if settings.DEBUG:
            paypal_api_root = "https://api.sandbox.paypal.com"
        else:
            paypal_api_root = "https://api.paypal.com"

        # https://developer.paypal.com/api/rest/authentication/
        oauth_url = f"{paypal_api_root}/v1/oauth2/token"
        payload = "grant_type=client_credentials"
        headers = {
            "accept": "application/json",
            "accept-language": "en_US",
            "content-type": "application/x-www-form-urlencoded",
        }
        auth = (settings.PAYPAL_CLIENT_ID, settings.PAYPAL_SECRET_KEY)

        # Get an OAuth token
        # Raises an error on a PayPal failure
        resp = requests.post(oauth_url, data=payload, headers=headers, auth=auth)
        resp.raise_for_status()
        access_token = resp.json()["access_token"]

        # Make the actual payout
        # https://developer.paypal.com/docs/api/payments.payouts-batch/v1/
        payout_url = "{paypal_api_root}/v1/payments/payouts"
        headers = {
            "accept": "application/json",
            "authorization": f"Bearer {access_token}",
            "content-type": "application/json",
        }
        payload = {
            "sender_batch_header": {
                "email_subject": f"EthicalAds Payout - {publisher}",
                "sender_batch_id": f"payout-{str(payout.id)}",
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "amount": {
                        "value": amount,
                        "currency": "USD",
                    },
                    "receiver": paypal_email,
                    "note": f"EthicalAds Payout - {publisher}",
                    "purpose": "SERVICES",
                },
            ],
        }
        resp = requests.post(payout_url, data=json.dumps(payload), headers=headers)
        resp.raise_for_status()

        return resp.json()["batch_header"]["payout_batch_id"]
