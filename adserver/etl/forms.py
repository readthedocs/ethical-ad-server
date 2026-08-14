"""Forms for ETL."""

from crispy_forms import layout
from crispy_forms.helper import FormHelper
from django import forms
from django.utils.translation import gettext_lazy as _
from django_countries import countries as djcountries

from ..models import Keyword
from ..models import Topic


class AudienceEstimatorForm(forms.Form):
    """Get traffic estimates for country/domain/topics/keywords."""

    countries = forms.CharField(
        max_length=1024,
        required=False,
        help_text=_(
            "A comma separated list of country codes. Multiple countries will result in a wider audience."
        ),
    )
    topics = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    keywords = forms.CharField(
        max_length=1024,
        required=False,
        help_text=_(
            "A comma separated list of keywords. Multiple keywords will result in a wider audience."
        ),
    )
    domains = forms.CharField(
        max_length=1024,
        required=False,
        help_text=_(
            "A comma separated list of domains. Multiple domains will result in a wider audience."
        ),
    )

    def __init__(self, *args, **kwargs):
        """Add the form helper and customize the look of the form."""
        super().__init__(*args, **kwargs)

        topics = Topic.objects.all().order_by("slug")
        self.fields["topics"].choices = [(t.slug, t.name) for t in topics]

        self.helper = FormHelper()

        self.helper.layout = layout.Layout(
            layout.Fieldset(
                _("Geo-targeting"),
                layout.Field("countries", placeholder=_("US, CA, GB")),
                css_class="my-3",
            ),
            layout.Fieldset(
                _("Keywords & Topics"),
                layout.Div(
                    layout.Div(
                        layout.Field("topics"),
                        css_class="form-group col-lg-6",
                    ),
                    layout.Div(
                        layout.Field("keywords", placeholder=_("django, flask")),
                        css_class="form-group col-lg-6",
                    ),
                    css_class="form-row",
                ),
                css_class="my-3",
            ),
            layout.Fieldset(
                _("Domains"),
                layout.Field(
                    "domains",
                    placeholder=_(
                        "docs.readthedocs.io, ethical-ad-server.readthedocs.io"
                    ),
                ),
                css_class="my-3",
            ),
            layout.Submit("submit", _("Get Estimate")),
            layout.HTML(
                "<p class='form-text small text-muted'>"
                + str(
                    _("Estimates can take a few minutes and query parquet offers data.")
                )
                + "</p>"
            ),
        )

    def clean_countries(self):
        data = self.cleaned_data["countries"]
        countries = [cc.strip() for cc in data.split(",") if len(cc.strip()) > 0]
        valid_countries = {c[0] for c in djcountries}
        for c in countries:
            if c not in valid_countries:
                raise forms.ValidationError(_("Invalid country code '%s'") % c)
        return countries

    def clean_keywords(self):
        data = self.cleaned_data["keywords"]
        keywords = [kw.strip().lower() for kw in data.split(",") if len(kw.strip()) > 0]
        valid_kws = {kw.slug for kw in Keyword.objects.all()}
        for kw in keywords:
            if kw not in valid_kws:
                raise forms.ValidationError(_("Unknown keyword '%s'") % kw)
        return keywords

    def clean_domains(self):
        data = self.cleaned_data["domains"]
        domains = [d.strip().lower() for d in data.split(",") if len(d.strip()) > 0]
        for d in domains:
            if "." not in d:
                raise forms.ValidationError(_("Invalid domain '%s'") % d)
        return domains
