"""Tests for LLM client and router: HTTP mocking, streaming, fallback logic.

Covers:
- LLMClient.chat_completion with mocked HTTP responses
- LLMClient.chat_completion_stream with SSE parsing
- Error handling: timeout, API errors, invalid JSON
- LLMRouter fallback from primary to light model
- LLMRouter streaming fallback
- get_llm_router singleton behavior
"""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx


class TestLLMClient:
    """Tests for the low-level LLMClient HTTP interactions."""

    @pytest.mark.asyncio
    async def test_chat_completion_success(self):
        """Successful chat completion returns message content."""
        from app.llm.client import LLMClient

        mock_response_data = {
            "choices": [{"message": {"content": "Hello world"}}]
        }

        client = LLMClient(
            base_url="http://test-api.local/v1",
            api_key="test-key",
            model="test-model",
        )

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = mock_response_data
        mock_http_response.raise_for_status = MagicMock()

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_http_response)
        mock_http_client.is_closed = False
        client._client = mock_http_client

        result = await client.chat_completion(
            messages=[{"role": "user", "content": "Hi"}]
        )

        assert result == "Hello world"
        mock_http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_completion_with_response_format(self):
        """Response format parameter is included in payload when provided."""
        from app.llm.client import LLMClient

        mock_response_data = {
            "choices": [{"message": {"content": '{"key": "value"}'}}]
        }

        client = LLMClient(
            base_url="http://test-api.local/v1",
            api_key="test-key",
            model="test-model",
        )

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = mock_response_data
        mock_http_response.raise_for_status = MagicMock()

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_http_response)
        mock_http_client.is_closed = False
        client._client = mock_http_client

        await client.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
            response_format={"type": "json_object"},
        )

        call_kwargs = mock_http_client.post.call_args
        payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        assert payload.get("response_format") == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_chat_completion_http_error_raises(self):
        """HTTP status errors are re-raised after logging."""
        from app.llm.client import LLMClient

        client = LLMClient(
            base_url="http://test-api.local/v1",
            api_key="test-key",
            model="test-model",
        )

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"
        error = httpx.HTTPStatusError(
            "Too Many Requests",
            request=MagicMock(),
            response=mock_response,
        )

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(side_effect=error)
        mock_http_client.is_closed = False
        client._client = mock_http_client

        with pytest.raises(httpx.HTTPStatusError):
            await client.chat_completion(
                messages=[{"role": "user", "content": "Hi"}]
            )

    @pytest.mark.asyncio
    async def test_chat_completion_generic_exception_raises(self):
        """Non-HTTP exceptions (e.g., timeout) are re-raised."""
        from app.llm.client import LLMClient

        client = LLMClient(
            base_url="http://test-api.local/v1",
            api_key="test-key",
            model="test-model",
        )

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(
            side_effect=httpx.ReadTimeout("Connection timed out")
        )
        mock_http_client.is_closed = False
        client._client = mock_http_client

        with pytest.raises(httpx.ReadTimeout):
            await client.chat_completion(
                messages=[{"role": "user", "content": "Hi"}]
            )

    @pytest.mark.asyncio
    async def test_chat_completion_stream_parses_sse(self):
        """Streaming correctly parses SSE data lines and yields content."""
        from app.llm.client import LLMClient

        client = LLMClient(
            base_url="http://test-api.local/v1",
            api_key="test-key",
            model="test-model",
        )

        # Simulate SSE lines
        sse_lines = [
            'data: {"choices": [{"delta": {"content": "Hello "}}]}',
            'data: {"choices": [{"delta": {"content": "world"}}]}',
            'data: [DONE]',
        ]

        async def mock_aiter_lines():
            for line in sse_lines:
                yield line

        mock_stream_response = AsyncMock()
        mock_stream_response.raise_for_status = MagicMock()
        mock_stream_response.aiter_lines = mock_aiter_lines
        mock_stream_response.__aenter__ = AsyncMock(return_value=mock_stream_response)
        mock_stream_response.__aexit__ = AsyncMock(return_value=False)

        mock_http_client = AsyncMock()
        mock_http_client.stream = MagicMock(return_value=mock_stream_response)
        mock_http_client.is_closed = False
        client._client = mock_http_client

        chunks = []
        async for chunk in client.chat_completion_stream(
            messages=[{"role": "user", "content": "Hi"}]
        ):
            chunks.append(chunk)

        assert chunks == ["Hello ", "world"]

    @pytest.mark.asyncio
    async def test_chat_completion_stream_skips_invalid_json(self):
        """Streaming skips malformed JSON lines without crashing."""
        from app.llm.client import LLMClient

        client = LLMClient(
            base_url="http://test-api.local/v1",
            api_key="test-key",
            model="test-model",
        )

        sse_lines = [
            'data: {invalid json}',
            'data: {"choices": [{"delta": {"content": "OK"}}]}',
            'data: [DONE]',
        ]

        async def mock_aiter_lines():
            for line in sse_lines:
                yield line

        mock_stream_response = AsyncMock()
        mock_stream_response.raise_for_status = MagicMock()
        mock_stream_response.aiter_lines = mock_aiter_lines
        mock_stream_response.__aenter__ = AsyncMock(return_value=mock_stream_response)
        mock_stream_response.__aexit__ = AsyncMock(return_value=False)

        mock_http_client = AsyncMock()
        mock_http_client.stream = MagicMock(return_value=mock_stream_response)
        mock_http_client.is_closed = False
        client._client = mock_http_client

        chunks = []
        async for chunk in client.chat_completion_stream(
            messages=[{"role": "user", "content": "Hi"}]
        ):
            chunks.append(chunk)

        assert chunks == ["OK"]

    @pytest.mark.asyncio
    async def test_close_client(self):
        """Closing the client sets _client to None."""
        from app.llm.client import LLMClient

        client = LLMClient(
            base_url="http://test-api.local/v1",
            api_key="test-key",
            model="test-model",
        )

        mock_http_client = AsyncMock()
        mock_http_client.is_closed = False
        client._client = mock_http_client

        await client.close()

        mock_http_client.aclose.assert_called_once()
        assert client._client is None


class TestLLMRouter:
    """Tests for LLMRouter fallback logic."""

    @pytest.mark.asyncio
    async def test_generate_with_fallback_primary_success(self):
        """Primary model succeeds — no fallback needed."""
        from app.llm.client import LLMRouter

        with patch("app.llm.client.get_settings") as mock_settings:
            settings = MagicMock()
            settings.llm_primary_base_url = "http://primary/v1"
            settings.llm_primary_api_key = "pk"
            settings.llm_primary_model = "primary-model"
            settings.llm_light_base_url = "http://light/v1"
            settings.llm_light_api_key = "lk"
            settings.llm_light_model = "light-model"
            mock_settings.return_value = settings

            router = LLMRouter()

        router.primary.chat_completion = AsyncMock(return_value="primary response")
        router.light.chat_completion = AsyncMock()

        result = await router.generate_with_fallback(
            messages=[{"role": "user", "content": "Hi"}]
        )

        assert result == "primary response"
        router.primary.chat_completion.assert_called_once()
        router.light.chat_completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_with_fallback_to_light(self):
        """Primary fails — falls back to light model."""
        from app.llm.client import LLMRouter

        with patch("app.llm.client.get_settings") as mock_settings:
            settings = MagicMock()
            settings.llm_primary_base_url = "http://primary/v1"
            settings.llm_primary_api_key = "pk"
            settings.llm_primary_model = "primary-model"
            settings.llm_light_base_url = "http://light/v1"
            settings.llm_light_api_key = "lk"
            settings.llm_light_model = "light-model"
            mock_settings.return_value = settings

            router = LLMRouter()

        router.primary.chat_completion = AsyncMock(
            side_effect=Exception("Primary down")
        )
        router.light.chat_completion = AsyncMock(return_value="light response")

        result = await router.generate_with_fallback(
            messages=[{"role": "user", "content": "Hi"}]
        )

        assert result == "light response"

    @pytest.mark.asyncio
    async def test_generate_with_fallback_both_fail(self):
        """Both models fail — exception is raised."""
        from app.llm.client import LLMRouter

        with patch("app.llm.client.get_settings") as mock_settings:
            settings = MagicMock()
            settings.llm_primary_base_url = "http://primary/v1"
            settings.llm_primary_api_key = "pk"
            settings.llm_primary_model = "primary-model"
            settings.llm_light_base_url = "http://light/v1"
            settings.llm_light_api_key = "lk"
            settings.llm_light_model = "light-model"
            mock_settings.return_value = settings

            router = LLMRouter()

        router.primary.chat_completion = AsyncMock(
            side_effect=Exception("Primary down")
        )
        router.light.chat_completion = AsyncMock(
            side_effect=Exception("Light also down")
        )

        with pytest.raises(Exception, match="Light also down"):
            await router.generate_with_fallback(
                messages=[{"role": "user", "content": "Hi"}]
            )

    @pytest.mark.asyncio
    async def test_generate_with_fallback_use_light_flag(self):
        """use_light=True uses light model first, primary as fallback."""
        from app.llm.client import LLMRouter

        with patch("app.llm.client.get_settings") as mock_settings:
            settings = MagicMock()
            settings.llm_primary_base_url = "http://primary/v1"
            settings.llm_primary_api_key = "pk"
            settings.llm_primary_model = "primary-model"
            settings.llm_light_base_url = "http://light/v1"
            settings.llm_light_api_key = "lk"
            settings.llm_light_model = "light-model"
            mock_settings.return_value = settings

            router = LLMRouter()

        router.light.chat_completion = AsyncMock(return_value="light first")
        router.primary.chat_completion = AsyncMock()

        result = await router.generate_with_fallback(
            messages=[{"role": "user", "content": "Hi"}],
            use_light=True,
        )

        assert result == "light first"
        router.light.chat_completion.assert_called_once()
        router.primary.chat_completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_stream_with_fallback_primary_success(self):
        """Streaming uses primary model when it works."""
        from app.llm.client import LLMRouter

        with patch("app.llm.client.get_settings") as mock_settings:
            settings = MagicMock()
            settings.llm_primary_base_url = "http://primary/v1"
            settings.llm_primary_api_key = "pk"
            settings.llm_primary_model = "primary-model"
            settings.llm_light_base_url = "http://light/v1"
            settings.llm_light_api_key = "lk"
            settings.llm_light_model = "light-model"
            mock_settings.return_value = settings

            router = LLMRouter()

        async def mock_primary_stream(*args, **kwargs):
            yield "chunk1"
            yield "chunk2"

        router.primary.chat_completion_stream = mock_primary_stream

        chunks = []
        async for chunk in router.generate_stream_with_fallback(
            messages=[{"role": "user", "content": "Hi"}]
        ):
            chunks.append(chunk)

        assert chunks == ["chunk1", "chunk2"]

    @pytest.mark.asyncio
    async def test_generate_stream_with_fallback_to_light(self):
        """Streaming falls back to light model on primary failure."""
        from app.llm.client import LLMRouter

        with patch("app.llm.client.get_settings") as mock_settings:
            settings = MagicMock()
            settings.llm_primary_base_url = "http://primary/v1"
            settings.llm_primary_api_key = "pk"
            settings.llm_primary_model = "primary-model"
            settings.llm_light_base_url = "http://light/v1"
            settings.llm_light_api_key = "lk"
            settings.llm_light_model = "light-model"
            mock_settings.return_value = settings

            router = LLMRouter()

        async def mock_primary_stream_fail(*args, **kwargs):
            raise Exception("Stream failed")
            yield  # Make it a generator  # noqa: E501

        async def mock_light_stream(*args, **kwargs):
            yield "fallback-chunk"

        router.primary.chat_completion_stream = mock_primary_stream_fail
        router.light.chat_completion_stream = mock_light_stream

        chunks = []
        async for chunk in router.generate_stream_with_fallback(
            messages=[{"role": "user", "content": "Hi"}]
        ):
            chunks.append(chunk)

        assert chunks == ["fallback-chunk"]


class TestGetLLMRouter:
    """Tests for the global LLM router singleton."""

    def test_get_llm_router_returns_same_instance(self):
        """get_llm_router returns the same instance on repeated calls."""
        import app.llm.client as client_module

        # Reset singleton
        client_module._llm_router = None

        with patch("app.llm.client.get_settings") as mock_settings:
            settings = MagicMock()
            settings.llm_primary_base_url = "http://p/v1"
            settings.llm_primary_api_key = "k"
            settings.llm_primary_model = "m"
            settings.llm_light_base_url = "http://l/v1"
            settings.llm_light_api_key = "k"
            settings.llm_light_model = "m"
            mock_settings.return_value = settings

            r1 = client_module.get_llm_router()
            r2 = client_module.get_llm_router()

        assert r1 is r2

        # Cleanup
        client_module._llm_router = None
