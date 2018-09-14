"""Ad server URLs"""

from django.conf.urls import url

from .views import dashboard, do_not_track, do_not_track_policy


urlpatterns = [
    url("^$", dashboard),
    # Do not Track
    url(r"^\.well-known/dnt/$", do_not_track, name="dnt-status"),
    url(r"^\.well-known/dnt-policy.txt$", do_not_track_policy, name="dnt-policy"),
]
