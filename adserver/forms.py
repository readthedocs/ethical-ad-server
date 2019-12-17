"""Forms for the ad server."""
from django import forms
from django.utils.translation import ugettext_lazy as _

from .models import Flight


class FlightAdminForm(forms.ModelForm):

    """The form for flights used by the Django Admin."""

    class Meta:
        model = Flight
        fields = (
            "name",
            "slug",
            "campaign",
            "start_date",
            "end_date",
            "live",
            "priority_multiplier",
            "cpc",
            "sold_clicks",
            "cpm",
            "sold_impressions",
            "targeting_parameters",
        )

    def clean(self):
        cpc = self.cleaned_data.get("cpc")
        cpm = self.cleaned_data.get("cpm")
        if cpc > 0 and cpm > 0:
            raise forms.ValidationError(_("A flight cannot have both CPC & CPM"))

        return self.cleaned_data
