"""Views for the administrator actions."""
import logging

from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from django.views.generic import FormView

from ..models import Advertiser
from .forms import CreateAdvertiserForm


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
