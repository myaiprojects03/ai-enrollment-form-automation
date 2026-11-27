"""The AI mapper's model call: one JSON answer that must match a schema.

Groq (free tier, OpenAI-compatible API) is the default; Claude is a drop-in for production. Both are plain HTTPS calls,
so there is no SDK to pin. Errors are raised as LLMError with a short reason and never include the prompt or reply.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

import httpx

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


class LLMError(Exception):
    """The model could not give a usable answer. str() is safe to store and show."""


class LLMClient(Protocol):
    name: str

    async def json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]: ...


async def _post(client: httpx.AsyncClient, url: str, headers: dict[str, str], body: dict[str, Any],
                attempts: int = 3) -> httpx.Response:
    for attempt in range(attempts):
        try:
            res = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException:
            if attempt == attempts - 1:
                raise LLMError("the model did not answer in time") from None
        except httpx.HTTPError:
            if attempt == attempts - 1:
                raise LLMError("could not reach the model") from None
        else:
            if res.status_code not in RETRY_STATUS or attempt == attempts - 1:
                return res
            wait = float(res.headers.get("retry-after", "0") or 0)
            await asyncio.sleep(min(max(wait, 1.5 * 2 ** attempt), 10))
            continue
        await asyncio.sleep(1.5 * 2 ** attempt)
    raise LLMError("could not reach the model")


def _parse(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        raise LLMError("the model's answer was not valid JSON") from None
    if not isinstance(data, dict):
        raise LLMError("the model's answer was not a JSON object")
    return data


class GroqClient:
    def __init__(self, api_key: str, model: str, timeout_s: float = 25.0):
        self.api_key, self.model, self.timeout_s = api_key, model, timeout_s
        self.name = f"groq:{model}"

    async def json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        body: dict[str, Any] = {
            "model": self.model, "temperature": 0, "max_completion_tokens": 4000,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "mapping", "strict": True,
                                                                         "schema": schema}},
        }
        if self.model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            res = await _post(client, GROQ_URL, headers, body)
            if res.status_code == 400 and "response_format" in res.text:
                # Older models only have JSON mode: same schema, stated in the prompt instead.
                body["response_format"] = {"type": "json_object"}
                body["messages"][0]["content"] = (system + "\n\nReply with JSON matching this schema:\n"
                                                  + json.dumps(schema))
                res = await _post(client, GROQ_URL, headers, body)
        if res.status_code == 401:
            raise LLMError("the Groq API key was refused")
        if res.status_code >= 400:
            raise LLMError(f"Groq answered {res.status_code}")
        try:
            content = res.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError):
            raise LLMError("unexpected reply from Groq") from None
        return _parse(content)


class AnthropicClient:
    """Claude, with the schema as a forced tool so the answer is always structured."""

    def __init__(self, api_key: str, model: str, timeout_s: float = 25.0):
        self.api_key, self.model, self.timeout_s = api_key, model, timeout_s
        self.name = f"anthropic:{model}"

    async def json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        body = {
            "model": self.model, "max_tokens": 4000, "temperature": 0, "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [{"name": "record_mapping", "description": "Record the field mapping.", "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": "record_mapping"},
        }
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            res = await _post(client, ANTHROPIC_URL, headers, body)
        if res.status_code == 401:
            raise LLMError("the Anthropic API key was refused")
        if res.status_code >= 400:
            raise LLMError(f"Anthropic answered {res.status_code}")
        try:
            block = next(b for b in res.json()["content"] if b.get("type") == "tool_use")
        except (KeyError, StopIteration, ValueError):
            raise LLMError("unexpected reply from Anthropic") from None
        if not isinstance(block.get("input"), dict):
            raise LLMError("unexpected reply from Anthropic")
        return block["input"]


def build_llm(provider: str, *, groq_api_key: str, groq_model: str, anthropic_api_key: str,
              anthropic_model: str) -> LLMClient | None:
    """None means rules only: structured records still map; free text waits for a person."""
    p = provider.strip().lower()
    if p == "none":
        return None
    if p == "anthropic":
        return AnthropicClient(anthropic_api_key, anthropic_model) if anthropic_api_key else None
    if p in ("groq", "auto", ""):
        if groq_api_key:
            return GroqClient(groq_api_key, groq_model)
        if p == "auto" and anthropic_api_key:
            return AnthropicClient(anthropic_api_key, anthropic_model)
        return None
    raise ValueError(f"unknown LLM_PROVIDER {provider!r}: use groq, anthropic, auto or none")
