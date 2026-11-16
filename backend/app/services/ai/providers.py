"""AI provider adapters.

One small interface, one adapter per vendor, plain HTTPS via httpx (no vendor SDKs).
Keys come from the server environment only and are never logged or returned.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import ProviderError

log = logging.getLogger(__name__)


@dataclass
class Completion:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class AIProvider(ABC):
    name: str

    def __init__(self, api_key: str, model: str, timeout: float, transport: httpx.BaseTransport | None = None) -> None:
        self._key = api_key
        self.model = model
        self._client = httpx.Client(timeout=timeout, transport=transport)

    @abstractmethod
    def complete(self, system: str, prompt: str, max_tokens: int = 900) -> Completion: ...

    def _post(self, url: str, headers: dict[str, str], body: dict) -> dict:
        try:
            response = self._client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"{self.name} did not respond in time.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach {self.name}: {type(exc).__name__}.") from exc
        if response.status_code in (401, 403):
            raise ProviderError(f"{self.name} rejected the API key (HTTP {response.status_code}). Check AI_API_KEY.")
        if response.status_code == 429:
            raise ProviderError(f"{self.name} rate limit reached. Try again shortly.")
        if response.status_code >= 400:
            log.warning("ai provider error", extra={"provider": self.name, "status": response.status_code})
            raise ProviderError(f"{self.name} returned HTTP {response.status_code}.")
        return response.json()


class AnthropicProvider(AIProvider):
    name = "Anthropic"
    url = "https://api.anthropic.com/v1/messages"

    def complete(self, system: str, prompt: str, max_tokens: int = 900) -> Completion:
        data = self._post(
            self.url,
            {"x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            {"model": self.model, "max_tokens": max_tokens, "system": system,
             "messages": [{"role": "user", "content": prompt}]},
        )
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        usage = data.get("usage", {})
        return Completion(text.strip(), data.get("model", self.model), usage.get("input_tokens"), usage.get("output_tokens"))


class OpenAIProvider(AIProvider):
    name = "OpenAI"
    url = "https://api.openai.com/v1/chat/completions"

    def complete(self, system: str, prompt: str, max_tokens: int = 900) -> Completion:
        data = self._post(
            self.url,
            {"authorization": f"Bearer {self._key}", "content-type": "application/json"},
            {"model": self.model, "max_tokens": max_tokens,
             "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
        )
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage", {})
        return Completion((choice.get("message", {}).get("content") or "").strip(), data.get("model", self.model),
                          usage.get("prompt_tokens"), usage.get("completion_tokens"))


PROVIDERS: dict[str, type[AIProvider]] = {"anthropic": AnthropicProvider, "openai": OpenAIProvider}


def provider_status(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    if s.ai_provider == "none":
        return {"configured": False, "provider": None, "model": None,
                "message": "No AI provider is configured. Answers below are statistical analysis computed by DataBridge. "
                           "To enable AI answers, set AI_PROVIDER, AI_API_KEY and AI_MODEL in the backend .env file."}
    if not s.ai_api_key:
        return {"configured": False, "provider": s.ai_provider, "model": s.ai_model,
                "message": f"AI_PROVIDER is '{s.ai_provider}' but AI_API_KEY is not set on the server."}
    if not s.ai_model:
        return {"configured": False, "provider": s.ai_provider, "model": None,
                "message": "AI_MODEL is not set. Set it to a model name available on your provider account."}
    return {"configured": True, "provider": s.ai_provider, "model": s.ai_model,
            "message": f"Connected to {PROVIDERS[s.ai_provider].name} ({s.ai_model}). "
                       "Connection is verified on the first question."}


def get_provider(settings: Settings | None = None, transport: httpx.BaseTransport | None = None) -> AIProvider | None:
    s = settings or get_settings()
    if not provider_status(s)["configured"]:
        return None
    return PROVIDERS[s.ai_provider](s.ai_api_key or "", s.ai_model or "", s.ai_timeout_seconds, transport)
