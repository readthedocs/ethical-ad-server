from urllib.parse import urlparse

from django.conf import settings
from pgvector.django import CosineDistance
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.renderers import StaticHTMLRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from adserver.analyzer.backends.st import SentenceTransformerAnalyzerBackend
from adserver.analyzer.models import AnalyzedUrl


if "adserver.analyzer" in settings.INSTALLED_APPS:

    class EmbeddingViewSet(APIView):
        """
        Returns a list of similar URLs and scores based on querying the AnalyzedURL embedding for an incoming URL.

        Example: http://localhost:5000/api/v1/similar/?url=https://www.gitbook.com/

        .. http:get:: /api/v1/embedding/

            Return a list of similar URLs and scores based on querying the AnalyzedURL embedding for an incoming URL

            :<json string url: **Required**. The URL to query for similar URLs and scores

            :>json int count: The number of similar URLs returned
            :>json array results: An array of similar URLs and scores
        """

        permission_classes = [AllowAny]

        def get(self, request):
            """Return a list of similar URLs and scores based on querying the AnalyzedURL embedding for an incoming URL."""
            url = request.query_params.get("url")

            if not url:
                return Response(
                    {"error": "url is required"}, status=status.HTTP_400_BAD_REQUEST
                )

            backend_instance = SentenceTransformerAnalyzerBackend(url)
            response = backend_instance.fetch()
            if not response:
                return Response(
                    {"error": "Not able to fetch content from URL"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            processed_text = backend_instance.get_content(response)
            analyzed_embedding = backend_instance.embedding(response)

            unfiltered_urls = (
                AnalyzedUrl.objects.filter(publisher__allow_paid_campaigns=True)
                .exclude(embedding=None)
                .annotate(distance=CosineDistance("embedding", analyzed_embedding))
                .order_by("distance")[:25]
            )

            # Filter urls to ensure each domain is unique
            unique_domains = set()
            urls = []
            for url in unfiltered_urls:
                domain = urlparse(url.url).netloc
                if domain not in unique_domains:
                    unique_domains.add(domain)
                    urls.append(url)

            if not len(urls) > 3:
                return Response(
                    {"error": "No similar URLs found"}, status=status.HTTP_404_NOT_FOUND
                )

            return Response(
                {
                    "count": len(urls),
                    "text": processed_text[:500],
                    "results": [[url.url, url.distance] for url in urls],
                }
            )
