"""OpenRouter chat transport; reasoning metadata stays in conversation history."""
from copy import deepcopy
from urllib.parse import urlsplit

import httpx

from app.core.config import get_settings


class OpenRouterUnavailable(Exception):
    """Sanitized error code. Never retain HTTP bodies, headers or credentials."""


class OpenRouterClient:
    def __init__(self, *, api_key=None, model=None, transport=None):
        settings = get_settings()
        self.api_key = settings.openrouter_api_key if api_key is None else api_key
        self.model = model or settings.openrouter_model
        self.url = settings.openrouter_api_url
        self.transport = transport
        self.timeout = settings.openrouter_timeout_seconds
        self.reasoning_enabled = settings.openrouter_reasoning_enabled
        self.max_tokens = settings.openrouter_max_tokens

    def complete(self, messages, *, response_format=None, max_tokens=None):
        if not self.api_key:
            raise OpenRouterUnavailable("openrouter_key_missing")
        # Credentials must only go to the configured OpenRouter API destination.
        parsed = urlsplit(self.url)
        if (parsed.scheme != "https" or parsed.netloc != "openrouter.ai"
                or parsed.path != "/api/v1/chat/completions" or parsed.query or parsed.fragment):
            raise OpenRouterUnavailable("openrouter_url_invalid")
        payload = {"model": self.model, "messages": deepcopy(messages),
            "reasoning": {"enabled": self.reasoning_enabled}, "max_tokens": max_tokens or self.max_tokens}
        if response_format:
            payload["response_format"] = response_format
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False, transport=self.transport) as client:
                response = client.post(self.url, headers={"Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json", "X-OpenRouter-Title": "ReconIQ"}, json=payload)
                if response.status_code != 200:
                    raise OpenRouterUnavailable(f"openrouter_http_{response.status_code}")
                data = response.json()
            if not isinstance(data, dict) or data.get("error"):
                raise OpenRouterUnavailable("openrouter_response_error")
            choice = data["choices"][0]
            message = choice["message"]
            if not isinstance(message, dict):
                raise OpenRouterUnavailable("openrouter_invalid_message")
            content = message.get("content")
            if choice.get("finish_reason") == "length":
                raise OpenRouterUnavailable("openrouter_output_limit")
            if not isinstance(content, str) or not content.strip() or message.get("tool_calls"):
                raise OpenRouterUnavailable("openrouter_invalid_message")
            result = {"role": "assistant", "content": content}
            if "reasoning_details" in message:
                result["reasoning_details"] = deepcopy(message["reasoning_details"])
            return result
        except OpenRouterUnavailable:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            raise OpenRouterUnavailable("openrouter_request_failed") from None
