"""Ad server views"""

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse, Http404


def do_not_track(request):
    """
    Returns the Do Not Track status for the user

    https://w3c.github.io/dnt/drafts/tracking-dnt.html#status-representation

    :raises: Http404 if ``settings.ADSERVER_DO_NOT_TRACK`` is ``False``
    """
    if not settings.ADSERVER_DO_NOT_TRACK:
        raise Http404

    dnt_header = request.META.get("HTTP_DNT")

    data = {"tracking": "N" if dnt_header == "1" else "T"}
    if settings.ADSERVER_PRIVACY_POLICY_URL:
        data["policy"] = settings.ADSERVER_PRIVACY_POLICY_URL

    # pylint: disable=redundant-content-type-for-json-response
    return JsonResponse(data, content_type="application/tracking-status+json")


def do_not_track_policy(request):
    """
    Returns the Do Not Track policy

    https://github.com/EFForg/dnt-guide#12-how-to-assert-dnt-compliance

    :raises: Http404 if ``settings.ADSERVER_DO_NOT_TRACK`` is ``False``
    """
    if not settings.ADSERVER_DO_NOT_TRACK:
        raise Http404

    return render(request, "adserver/dnt-policy.txt", content_type="text/plain")


@login_required
def dashboard(request):
    return render(
        request, "adserver/dashboard.html", {"version": settings.ADSERVER_VERSION}
    )
