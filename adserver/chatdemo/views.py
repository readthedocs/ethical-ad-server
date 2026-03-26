"""Views for the AI chat demo with ethical ad targeting."""

import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView


log = logging.getLogger(__name__)


class ChatDemoView(TemplateView):
    """Serve the chat demo HTML page."""

    template_name = "adserver/chatdemo/chat.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["publisher_slug"] = getattr(
            settings, "ADSERVER_CHAT_DEMO_PUBLISHER", ""
        )
        return context


@method_decorator(csrf_exempt, name="dispatch")
class ChatCompletionProxyView(View):
    """
    Proxy chat completion requests to OpenAI.

    This keeps the OpenAI API key on the server side
    and uses a cheap model (gpt-4o-mini) for completions.
    """

    OPENAI_MODEL = "gpt-4o-mini"

    def post(self, request):
        api_key = getattr(settings, "OPENAI_API_KEY", None)
        if not api_key:
            return JsonResponse(
                {"error": "OpenAI API key not configured on the server"},
                status=500,
            )

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        messages = body.get("messages", [])
        if not messages:
            return JsonResponse({"error": "No messages provided"}, status=400)

        # Limit conversation length to prevent abuse
        messages = messages[:50]

        try:
            import openai

            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=self.OPENAI_MODEL,
                messages=messages,
                max_tokens=1024,
                temperature=0.7,
            )

            return JsonResponse(
                {
                    "content": response.choices[0].message.content,
                    "model": response.model,
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                    },
                }
            )

        except Exception:
            log.exception("OpenAI chat completion failed")
            return JsonResponse(
                {"error": "Chat completion request failed"},
                status=502,
            )
