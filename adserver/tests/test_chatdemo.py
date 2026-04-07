"""Tests for the chatdemo app: embedding utilities, views, and related task."""

import json
import sys
from unittest import mock

from django.test import Client
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from ..chatdemo.embedding import _embedding_cache_key
from ..chatdemo.embedding import cosine_similarity
from ..chatdemo.embedding import get_prompt_embedding
from ..chatdemo.embedding import get_prompt_niche_weights
from .common import BaseAdModelsTestCase


def _ensure_mock_module(name):
    """Inject a MagicMock into sys.modules so ``import <name>`` succeeds."""
    if name not in sys.modules:
        sys.modules[name] = mock.MagicMock()


# Ensure optional third-party packages are importable even if not installed.
_ensure_mock_module("openai")
_ensure_mock_module("boto3")
_ensure_mock_module("redis")


class CosineSimTest(TestCase):
    """Tests for the cosine_similarity helper."""

    def test_identical_vectors(self):
        vec = [1.0, 0.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(vec, vec), 1.0)

    def test_orthogonal_vectors(self):
        self.assertAlmostEqual(
            cosine_similarity([1, 0, 0], [0, 1, 0]),
            0.0,
        )

    def test_opposite_vectors(self):
        self.assertAlmostEqual(
            cosine_similarity([1, 0], [-1, 0]),
            -1.0,
        )

    def test_empty_or_mismatched(self):
        self.assertEqual(cosine_similarity([], []), 0.0)
        self.assertEqual(cosine_similarity(None, None), 0.0)
        self.assertEqual(cosine_similarity([1], [1, 2]), 0.0)

    def test_zero_magnitude(self):
        self.assertEqual(cosine_similarity([0, 0], [1, 1]), 0.0)


class EmbeddingCacheKeyTest(TestCase):
    """Tests for _embedding_cache_key."""

    def test_deterministic(self):
        key1 = _embedding_cache_key("hello world")
        key2 = _embedding_cache_key("hello world")
        self.assertEqual(key1, key2)

    def test_case_insensitive(self):
        self.assertEqual(
            _embedding_cache_key("Hello"),
            _embedding_cache_key("hello"),
        )

    def test_strips_whitespace(self):
        self.assertEqual(
            _embedding_cache_key("  hello  "),
            _embedding_cache_key("hello"),
        )


class GetPromptEmbeddingTest(TestCase):
    """Tests for get_prompt_embedding."""

    def test_empty_input_returns_none(self):
        self.assertIsNone(get_prompt_embedding(""))
        self.assertIsNone(get_prompt_embedding(None))
        self.assertIsNone(get_prompt_embedding("   "))

    @override_settings(OPENAI_API_KEY=None)
    def test_no_api_key_returns_none(self):
        self.assertIsNone(get_prompt_embedding("some text"))

    @override_settings(OPENAI_API_KEY="test-key")
    @mock.patch("adserver.chatdemo.embedding.cache")
    def test_cache_hit(self, mock_cache):
        mock_cache.get.return_value = [0.1, 0.2, 0.3]
        result = get_prompt_embedding("cached text")
        self.assertEqual(result, [0.1, 0.2, 0.3])

    @override_settings(OPENAI_API_KEY="test-key")
    @mock.patch("adserver.chatdemo.embedding.cache")
    def test_openai_call(self, mock_cache):
        mock_cache.get.return_value = None  # cache miss

        mock_embedding_data = mock.MagicMock()
        mock_embedding_data.embedding = [0.5, 0.6, 0.7]
        mock_response = mock.MagicMock()
        mock_response.data = [mock_embedding_data]

        with mock.patch("openai.OpenAI") as mock_openai_cls:
            mock_client = mock.MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.embeddings.create.return_value = mock_response

            result = get_prompt_embedding("test prompt")

        self.assertEqual(result, [0.5, 0.6, 0.7])
        mock_cache.set.assert_called_once()

    @override_settings(OPENAI_API_KEY="test-key")
    @mock.patch("adserver.chatdemo.embedding.cache")
    def test_openai_exception_returns_none(self, mock_cache):
        mock_cache.get.return_value = None

        with mock.patch("openai.OpenAI") as mock_openai_cls:
            mock_client = mock.MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.embeddings.create.side_effect = Exception("API down")

            result = get_prompt_embedding("fail text")

        self.assertIsNone(result)


class GetPromptNicheWeightsTest(BaseAdModelsTestCase):
    """Tests for get_prompt_niche_weights."""

    @mock.patch("adserver.chatdemo.embedding.get_prompt_embedding")
    def test_no_embedding_returns_empty(self, mock_embed):
        mock_embed.return_value = None
        result = get_prompt_niche_weights("test", [self.flight])
        self.assertEqual(result, {})

    @mock.patch("adserver.chatdemo.embedding._get_advertiser_embedding")
    @mock.patch("adserver.chatdemo.embedding.get_prompt_embedding")
    def test_returns_distance_dict(self, mock_embed, mock_ad_embed):
        mock_embed.return_value = [1.0, 0.0, 0.0]
        mock_ad_embed.return_value = [1.0, 0.0, 0.0]

        result = get_prompt_niche_weights("test", [self.flight])
        self.assertIn(self.advertiser, result)
        self.assertAlmostEqual(result[self.advertiser], 0.0)  # identical = distance 0

    @mock.patch("adserver.chatdemo.embedding._get_advertiser_embedding")
    @mock.patch("adserver.chatdemo.embedding.get_prompt_embedding")
    def test_no_ad_embedding_skips(self, mock_embed, mock_ad_embed):
        mock_embed.return_value = [1.0, 0.0]
        mock_ad_embed.return_value = None

        result = get_prompt_niche_weights("test", [self.flight])
        self.assertEqual(result, {})


class ChatDemoViewTest(TestCase):
    """Tests for the ChatDemoView template view."""

    @override_settings(ADSERVER_CHAT_DEMO_PUBLISHER="test-pub")
    def test_get_renders(self):
        url = reverse("chatdemo:chat-demo")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "test-pub")


class ChatCompletionProxyViewTest(TestCase):
    """Tests for the ChatCompletionProxyView."""

    def setUp(self):
        self.url = reverse("chatdemo:chat-completion")
        self.client = Client()

    @override_settings(OPENAI_API_KEY=None)
    def test_no_api_key(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 500)
        self.assertIn("error", resp.json())

    @override_settings(OPENAI_API_KEY="test-key")
    def test_invalid_json(self):
        resp = self.client.post(
            self.url,
            data="not json",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    @override_settings(OPENAI_API_KEY="test-key")
    def test_no_messages(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({"messages": []}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    @override_settings(OPENAI_API_KEY="test-key")
    def test_successful_completion(self):
        mock_choice = mock.MagicMock()
        mock_choice.message.content = "Hello from AI"
        mock_usage = mock.MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 5
        mock_response = mock.MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "gpt-4o-mini"
        mock_response.usage = mock_usage

        with mock.patch("openai.OpenAI") as mock_openai_cls:
            mock_client = mock.MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            resp = self.client.post(
                self.url,
                data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}),
                content_type="application/json",
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["content"], "Hello from AI")
        self.assertEqual(data["model"], "gpt-4o-mini")

    @override_settings(OPENAI_API_KEY="test-key")
    def test_openai_failure(self):
        with mock.patch("openai.OpenAI") as mock_openai_cls:
            mock_client = mock.MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.side_effect = Exception("fail")

            resp = self.client.post(
                self.url,
                data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}),
                content_type="application/json",
            )

        self.assertEqual(resp.status_code, 502)


class PublishCeleryQueueDepthTest(TestCase):
    """Tests for the publish_celery_queue_depth task."""

    @mock.patch("boto3.client")
    @mock.patch("redis.Redis.from_url")
    @override_settings(
        CELERY_BROKER_URL="redis://localhost:6379/0",
        AWS_S3_REGION_NAME="us-east-1",
    )
    def test_publishes_metric(self, mock_redis_from_url, mock_boto_client):
        from ..tasks import publish_celery_queue_depth

        mock_redis = mock.MagicMock()
        mock_redis.llen.return_value = 5
        mock_redis_from_url.return_value = mock_redis

        mock_cw = mock.MagicMock()
        mock_boto_client.return_value = mock_cw

        publish_celery_queue_depth()

        mock_cw.put_metric_data.assert_called_once()
        call_kwargs = mock_cw.put_metric_data.call_args[1]
        self.assertEqual(call_kwargs["Namespace"], "EthicalAds/Celery")
        self.assertEqual(call_kwargs["MetricData"][0]["Value"], 15)  # 5 * 3 queues

    @mock.patch("redis.Redis.from_url")
    @override_settings(CELERY_BROKER_URL="redis://localhost:6379/0")
    def test_redis_failure(self, mock_redis_from_url):
        from ..tasks import publish_celery_queue_depth

        mock_redis_from_url.side_effect = Exception("connection failed")

        # Should not raise
        publish_celery_queue_depth()

    @mock.patch("boto3.client")
    @mock.patch("redis.Redis.from_url")
    @override_settings(
        CELERY_BROKER_URL="redis://localhost:6379/0",
        AWS_S3_REGION_NAME="us-east-1",
    )
    def test_cloudwatch_failure(self, mock_redis_from_url, mock_boto_client):
        from ..tasks import publish_celery_queue_depth

        mock_redis = mock.MagicMock()
        mock_redis.llen.return_value = 0
        mock_redis_from_url.return_value = mock_redis

        mock_cw = mock.MagicMock()
        mock_cw.put_metric_data.side_effect = Exception("cloudwatch fail")
        mock_boto_client.return_value = mock_cw

        # Should not raise
        publish_celery_queue_depth()
