"""Views for the administrator actions."""
import datetime
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.template.loader import get_template
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django.views.generic import DetailView
from django.views.generic import FormView
from django.views.generic import TemplateView

from ..constants import PAID
from ..models import Advertiser
from ..models import Publisher
from .forms import CreateAdvertiserForm
from .forms import CreatePublisherForm
from .forms import StartPublisherPayoutForm
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
    * all: Show all publishers, not just folks with payouts due
    * publisher: Filter to a specific publisher
    * limit: Show only up to ``limit`` publishers, mostly for testing & debugging
    """

    template_name = "adserver/staff/publisher-payout-list.html"
    # Two hours should be enough to run most payouts
    CACHE_SECONDS = 7200

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        limit = int(self.request.GET.get("limit", 0))
        all_publishers = self.request.GET.get("all")
        publisher_slug = self.request.GET.get("publisher")

        queryset = Publisher.objects.all()
        if publisher_slug:
            queryset = queryset.filter(slug__startswith=publisher_slug)

        if limit:
            queryset = queryset[:limit]

        payouts = {}

        for publisher in queryset:
            data = generate_publisher_payout_data(
                publisher, include_current_report=False
            )

            # Cache payout data to make running payouts faster
            data = cache.get(f"payout-{publisher.pk}")
            if not data:
                data = generate_publisher_payout_data(publisher)
                cache.set(f"payout-{publisher.pk}", data, self.CACHE_SECONDS)

            report = data.get("due_report")
            if not report:
                continue

            due_balance = report["total"]["revenue_share"]
            due_str = "{:.2f}".format(due_balance)
            ctr = report["total"]["ctr"]
            ctr_str = "{:.2f}".format(ctr)

            if (
                due_balance < float(settings.ADSERVER_MINIMUM_PAYOUT)
                and not all_publishers
            ):
                continue

            payouts_url = generate_absolute_url(
                reverse("publisher_payouts", kwargs={"publisher_slug": publisher.slug})
            )
            settings_url = generate_absolute_url(
                reverse("publisher_settings", kwargs={"publisher_slug": publisher.slug})
            )
            payout_context = dict(
                payouts_url=payouts_url,
                settings_url=settings_url,
                publisher=publisher,
                total=due_str,
                ctr=ctr_str,
                **data,
            )

            current_payout = publisher.payouts.filter(
                date__month=timezone.now().month,
                date__year=timezone.now().year,
            ).first()
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
        initial["amount"] = "%.2f" % self.data["due_report"]["total"]["revenue_share"]
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
        kwargs["amount"] = "%.2f" % self.data["due_report"]["total"]["revenue_share"]
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


class PublisherFinishPayoutView(StaffUserMixin, DetailView):

    """Start a payout for a publisher."""

    template_name = "adserver/staff/publisher-payout-finish.html"

    def get_object(self, queryset=None):
        self.publisher = get_object_or_404(
            Publisher, slug=self.kwargs["publisher_slug"]
        )
        self.payout = self.publisher.payouts.exclude(status=PAID).first()
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
