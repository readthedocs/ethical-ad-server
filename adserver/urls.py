"""Ad server URLs"""
from django.conf.urls import url

from .views import dashboard
from .views import do_not_track
from .views import do_not_track_policy


urlpatterns = [
    url("^$", dashboard, name="dashboard-home"),
    # Do not Track
    url(r"^\.well-known/dnt/$", do_not_track, name="dnt-status"),
    url(r"^\.well-known/dnt-policy.txt$", do_not_track_policy, name="dnt-policy"),
]
