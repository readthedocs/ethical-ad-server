from django.conf import settings
from pgvector.django import CosineDistance
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from adserver.analyzer.backends.st import SentenceTransformerAnalyzerBackend
from adserver.analyzer.models import AnalyzedUrl


if "adserver.analyzer" in settings.INSTALLED_APPS:

    class EmbeddingViewSet(APIView):
        """
        Returns a list of similar URLs and scores based on querying the AnalyzedURL embedding for an incoming URL.

        .. http:get:: /api/v1/embedding/

            Return a list of similar URLs and scores based on querying the AnalyzedURL embedding for an incoming URL

            :<json string url: **Required**. The URL to query for similar URLs and scores

            :>json int count: The number of similar URLs returned
            :>json array results: An array of similar URLs and scores
        """

        def get(self, request):
            """Return a list of similar URLs and scores based on querying the AnalyzedURL embedding for an incoming URL."""
            url = request.query_params.get("url")

            if not url:
                return Response(
                    {"error": "url is required"}, status=status.HTTP_400_BAD_REQUEST
                )

            backend_instance = SentenceTransformerAnalyzerBackend(url)
            response = backend_instance.fetch()
            processed_text = backend_instance.get_content(response)
            analyzed_embedding = backend_instance.embedding(response)

            urls = (
                AnalyzedUrl.objects.exclude(embedding=None)
                .annotate(distance=CosineDistance("embedding", analyzed_embedding))
                .order_by("distance")[:10]
            )

            return Response(
                {
                    "count": len(urls),
                    "text": processed_text[:500],
                    "results": [[url.url, url.distance] for url in urls],
                }
            )
