"""LLM client for calling OpenAI-compatible APIs.

Memory-safety: Each LLMClient now uses bounded connection pools and
explicit per-operation timeouts to prevent unbounded memory growth
when the remote API is slow, returns huge responses, or hangs.
"""

import json
import logging
from typing import AsyncGenerator, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Maximum response body size we accept from the LLM API (10 MB)
_MAX_LLM_RESPONSE_SIZE = 10 * 1024 * 1024


class LLMClient:
    """Async LLM client using httpx."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx client with bounded connection pool."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=self.timeout,
                    write=10.0,
                    pool=30.0,
                ),
                limits=httpx.Limits(
                    max_connections=6,
                    max_keepalive_connections=2,
                    keepalive_expiry=15.0,
                ),
            )
        return self._client

    async def close(self) -> None:
        """Close the httpx client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def chat_completion(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict] = None,
    ) -> str:
        """Send a chat completion request."""
        settings = get_settings()
        client = await self._get_client()

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or settings.llm_temperature,
            "max_tokens": max_tokens or settings.llm_max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        try:
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            # Guard against unexpectedly large responses
            body_size = len(response.content)
            if body_size > _MAX_LLM_RESPONSE_SIZE:
                logger.error(
                    f"LLM API response too large: {body_size / 1024 / 1024:.1f} MB "
                    f"(limit {_MAX_LLM_RESPONSE_SIZE / 1024 / 1024:.0f} MB)"
                )
                raise ValueError("LLM API response exceeds safety size limit")
            data = response.json()
            choices = data.get("choices")
            if not choices:
                logger.error(f"LLM API returned empty choices: {data}")
                raise ValueError("LLM API returned empty choices")
            return choices[0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM API error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            raise

    async def chat_completion_stream(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """Send a streaming chat completion request."""
        settings = get_settings()
        client = await self._get_client()

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or settings.llm_temperature,
            "max_tokens": max_tokens or settings.llm_max_tokens,
            "stream": True,
        }

        try:
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices")
                            if not choices:
                                logger.warning(f"Empty choices in streaming chunk: {data_str[:200]}")
                                continue
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM streaming API error: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"LLM streaming API call failed: {e}")
            raise


class LLMRouter:
    """Router for selecting the appropriate LLM client."""

    def __init__(self):
        settings = get_settings()
        self.primary = LLMClient(
            base_url=settings.llm_primary_base_url,
            api_key=settings.llm_primary_api_key,
            model=settings.llm_primary_model,
        )
        self.light = LLMClient(
            base_url=settings.llm_light_base_url,
            api_key=settings.llm_light_api_key,
            model=settings.llm_light_model,
        )

    async def close(self) -> None:
        """Close all clients."""
        await self.primary.close()
        await self.light.close()

    async def generate_with_fallback(
        self,
        messages: list[dict],
        use_light: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict] = None,
    ) -> str:
        """Generate with fallback from primary to light model."""
        client = self.light if use_light else self.primary
        fallback_client = self.primary if use_light else self.light

        try:
            return await client.chat_completion(
                messages, temperature, max_tokens, response_format
            )
        except Exception as e:
            logger.warning(f"Primary model failed ({e}), trying fallback...")
            try:
                return await fallback_client.chat_completion(
                    messages, temperature, max_tokens, response_format
                )
            except Exception as fallback_error:
                logger.error(f"Fallback model also failed: {fallback_error}")
                raise

    async def generate_stream_with_fallback(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """Generate streaming with fallback."""
        try:
            async for chunk in self.primary.chat_completion_stream(
                messages, temperature, max_tokens
            ):
                yield chunk
        except Exception as e:
            logger.warning(f"Primary model streaming failed ({e}), trying fallback...")
            async for chunk in self.light.chat_completion_stream(
                messages, temperature, max_tokens
            ):
                yield chunk


# Global LLM router instance
_llm_router: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    """Get the global LLM router."""
    global _llm_router
    if _llm_router is None:
        _llm_router = LLMRouter()
    return _llm_router
