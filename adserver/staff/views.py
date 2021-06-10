"""Views for the administrator actions."""
import logging

from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from django.views.generic import FormView
from django.views.generic import TemplateView

from ..models import Advertiser
from .forms import CreateAdvertiserForm
from adserver.utils import generate_absolute_url
from adserver.utils import generate_publisher_payout_data


log = logging.getLogger(__name__)  # noqa


class StaffUserMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_staff


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


class PublisherPayoutView(StaffUserMixin, TemplateView):
    """
    A view listing all the payouts that are due in the upcoming month

    Has the following arguments:
    * all: Show all publishers, not just folks with payouts due
    * publisher: Filter to a specific publisher
    * limit: Show only up to ``limit`` publishers, mostly for testing & debugging
    """

    template_name = "adserver/staff/publisher-payout.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        limit = self.request.GET.get("limit", 50)
        all_publishers = self.request.GET.get("all")
        publisher_slug = self.request.GET.get("publisher")

        queryset = self.get_queryset()
        if publisher_slug:
            queryset = queryset.filter(slug=publisher_slug)
        if not all_publishers:
            queryset = queryset.filter(payouts__isnull=False, allow_paid_campaigns=True)

        payouts = {}

        for publisher in queryset[:limit]:
            data = generate_publisher_payout_data(publisher)
            report = data.get("due_report")
            report_url = data.get("due_report_url")
            if not report:
                if not all_publishers:
                    # Skip publishers without due money
                    continue
                report = data.get("current_report")
                report_url = data.get("current_report_url")

            due_balance = report["total"]["revenue_share"]
            due_str = "{:.2f}".format(due_balance)
            ctr = report["total"]["ctr"]
            ctr_str = "{:.2f}".format(ctr)

            if due_balance < float(50) and not all_publishers:
                continue

            payouts_url = generate_absolute_url(
                "publisher_payouts", kwargs={"publisher_slug": publisher.slug}
            )
            settings_url = generate_absolute_url(
                "publisher_settings", kwargs={"publisher_slug": publisher.slug}
            )
            payout_context = dict(
                report=report,
                report_url=report_url,
                payouts_url=payouts_url,
                settings_url=settings_url,
                publisher=publisher,
                total=due_str,
                ctr=ctr_str,
                **data,
            )
            payouts[publisher.slug] = payout_context
        context["payouts"] = payouts
        return context
