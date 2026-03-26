"""URL configuration for the chat demo."""

from django.urls import path

from .views import ChatCompletionProxyView
from .views import ChatDemoView


app_name = "chatdemo"

urlpatterns = [
    path("", ChatDemoView.as_view(), name="chat-demo"),
    path("completion/", ChatCompletionProxyView.as_view(), name="chat-completion"),
]
