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
        renderer_classes = [StaticHTMLRenderer]

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

            urls = (
                AnalyzedUrl.objects.exclude(embedding=None)
                .annotate(distance=CosineDistance("embedding", analyzed_embedding))
                .order_by("distance")[:10]
            )

            return Response(
                f"""
                <h2>Results:</h2>
                <ul>
                    <li><a href="{urls[0].url}">{urls[0].url}</a></li>
                    <li><a href="{urls[1].url}">{urls[1].url}</a></li>
                    <li><a href="{urls[2].url}">{urls[2].url}</a></li>
                    <li><a href="{urls[3].url}">{urls[3].url}</a></li>
                </ul>
                <h2>
                Text:
                </h2>
                <textarea style="height:100%; width:80%" disabled>
                {processed_text}
                </textarea>
                """
            )
