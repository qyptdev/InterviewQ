"""LLM-related schemas."""

from pydantic import BaseModel
from typing import Optional


class ChatMessage(BaseModel):
    """Chat message schema."""
    role: str  # system, user, assistant
    content: str


class LLMRequest(BaseModel):
    """LLM request schema."""
    messages: list[ChatMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    use_light: bool = False


class LLMResponse(BaseModel):
    """LLM response schema."""
    content: str
    model: str
    usage: Optional[dict] = None
