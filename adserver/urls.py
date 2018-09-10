"""Ad server URLs"""

from django.conf.urls import url

from .views import dashboard


urlpatterns = [url("^$", dashboard)]
