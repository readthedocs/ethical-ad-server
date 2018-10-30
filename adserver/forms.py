"""Forms for the ad server"""
from django import forms
from django.utils.translation import ugettext_lazy as _

from .models import Flight


class FlightForm(forms.ModelForm):
    class Meta:
        model = Flight
        fields = "__all__"

    def clean(self):
        cpc = self.cleaned_data.get("cpc")
        cpm = self.cleaned_data.get("cpm")
        if cpc > 0 and cpm > 0:
            raise forms.ValidationError(_("A flight cannot have both CPC & CPM"))

        return self.cleaned_data
