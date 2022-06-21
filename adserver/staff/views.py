"""Views for the administrator actions."""
import datetime
import logging

from django.conf import settings
from django.contrib import messages
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

from ..constants import PAID
from ..mixins import StaffUserMixin
from ..models import Advertiser
from ..models import Publisher
from .forms import CreateAdvertiserForm
from .forms import CreatePublisherForm
from .forms import StartPublisherPayoutForm
from adserver.utils import generate_publisher_payout_data


log = logging.getLogger(__name__)  # noqa


class CreateAdvertiserView(StaffUserMixin, FormView):
    form_class = CreateAdvertiserForm
    model = Advertiser
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


class CreatePublisherView(StaffUserMixin, FormView):
    form_class = CreatePublisherForm
    model = Publisher
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
    """

    template_name = "adserver/staff/publisher-payout-list.html"
    # Cache for 24 hours so we can finish payouts
    CACHE_SECONDS = 3600 * 24

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        publisher_slug = self.request.GET.get("publisher")
        first = self.request.GET.get("first", "")
        paid = self.request.GET.get("paid", "")

        queryset = Publisher.objects.filter(skip_payouts=False)
        if publisher_slug:
            queryset = queryset.filter(slug__startswith=publisher_slug)

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

            if (paid == "True" and current_payout.status == PAID) or (
                paid == "False"
                and current_payout is None
                or current_payout.status != PAID
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
        context["boolean_options"] = [["", "---"], ["True", "True"], ["False", "False"]]
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
        )
        initial["sender"] = "EthicalAds by Read the Docs"
        initial["subject"] = f"EthicalAds Payout - {self.publisher.name}"
        initial["body"] = email_html
        initial["amount"] = "%.2f" % self.get_amount(self.data["due_report"])
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
        self.payout.status = PAID
        self.payout.save()
        messages.success(self.request, _("Successfully updated payout to paid status"))
        return redirect(self.payout.get_absolute_url())
