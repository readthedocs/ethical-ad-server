from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard(request):
    return render(
        request, "adserver/dashboard.html", {"version": settings.ADSERVER_VERSION}
    )
