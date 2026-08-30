"""
Provider adapters.

Each free-tier provider speaks a slightly different API shape. Rather than
special-casing providers throughout the codebase, every adapter exposes the
same two functions so the key pool and /chat endpoint don't need to know
which provider they're talking to:

    async def stream_chat(api_key, model, messages) -> yields text chunks
    async def test_validity(api_key, model) -> "valid" | "invalid" | "rate_limited"

To add a new provider later: write one more adapter with this shape and
register it in PROVIDER_ADAPTERS below — nothing else needs to change.
"""

import json
from typing import AsyncGenerator, List, Dict

import httpx

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


# ---------------------------------------------------------------------------
# OpenAI-compatible providers (Groq, OpenRouter, and most others use this
# exact request/response shape for /chat/completions)
# ---------------------------------------------------------------------------

def _openai_compatible(base_url: str, extra_headers: dict | None = None):
    extra_headers = extra_headers or {}

    async def stream_chat(api_key: str, model: str, messages: List[Dict]) -> AsyncGenerator[str, None]:
        payload = {"model": model, "messages": messages, "stream": True}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            **extra_headers,
        }
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            async with client.stream("POST", base_url, json=payload, headers=headers) as resp:
                if resp.status_code == 429:
                    raise RateLimitError(f"{base_url} rate limited")
                if resp.status_code in (401, 403):
                    raise InvalidKeyError(f"{base_url} rejected key: {resp.status_code}")
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise ProviderError(f"{base_url} error {resp.status_code}: {body.decode()[:200]}")

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[len("data: "):]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except (KeyError, IndexError, json.JSONDecodeError):
                        continue

    async def test_validity(api_key: str, model: str) -> str:
        payload = {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            **extra_headers,
        }
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.post(base_url, json=payload, headers=headers)
            if resp.status_code == 200:
                return "valid"
            if resp.status_code == 429:
                return "rate_limited"
            if resp.status_code in (401, 403):
                return "invalid"
            return "invalid"
        except httpx.HTTPError:
            return "invalid"

    return stream_chat, test_validity


class RateLimitError(Exception):
    pass


class InvalidKeyError(Exception):
    pass


class ProviderError(Exception):
    pass


groq_stream_chat, groq_test_validity = _openai_compatible(
    "https://api.groq.com/openai/v1/chat/completions"
)

openrouter_stream_chat, openrouter_test_validity = _openai_compatible(
    "https://openrouter.ai/api/v1/chat/completions",
    extra_headers={"HTTP-Referer": "http://localhost", "X-Title": "Personal AI Agent"},
)


# ---------------------------------------------------------------------------
# Gemini — different request/response shape, no native SSE token stream via
# this simple approach, so we fetch the full reply and yield it as one chunk.
# Good enough for Phase 2; can be upgraded to real streaming later.
# ---------------------------------------------------------------------------

async def gemini_stream_chat(api_key: str, model: str, messages: List[Dict]) -> AsyncGenerator[str, None]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
                for m in messages]
    payload = {"contents": contents}

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(url, json=payload)
    if resp.status_code == 429:
        raise RateLimitError("gemini rate limited")
    if resp.status_code in (401, 403):
        raise InvalidKeyError(f"gemini rejected key: {resp.status_code}")
    if resp.status_code != 200:
        raise ProviderError(f"gemini error {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        text = ""
    yield text


async def gemini_test_validity(api_key: str, model: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}],
               "generationConfig": {"maxOutputTokens": 1}}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code == 200:
            return "valid"
        if resp.status_code == 429:
            return "rate_limited"
        return "invalid"
    except httpx.HTTPError:
        return "invalid"


async def gemini_vision_extract(api_key: str, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """One-shot text extraction from an image via Gemini's vision input —
    used only as a fallback when Tesseract OCR produces too little text."""
    import base64

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": "Extract all text visible in this image, verbatim. Return only the extracted text, nothing else."},
                {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode()}},
            ],
        }]
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(url, json=payload)
    if resp.status_code != 200:
        raise ProviderError(f"gemini vision error {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        return ""


PROVIDER_ADAPTERS = {
    "groq": (groq_stream_chat, groq_test_validity),
    "openrouter": (openrouter_stream_chat, openrouter_test_validity),
    "gemini": (gemini_stream_chat, gemini_test_validity),
}

# Sensible default model per provider — used for BYOK so the user only
# needs to paste a key, not also pick a model name.
DEFAULT_MODELS = {
    "groq": "qwen/qwen3.6-27b",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "gemini": "gemini-2.0-flash",
}

# Where a user goes to create a free key for each provider — used to build
# the guided links in the inline BYOK prompt.
KEY_CREATION_LINKS = {
    "groq": "https://console.groq.com/keys",
    "gemini": "https://aistudio.google.com/apikey",
    "openrouter": "https://openrouter.ai/keys",
}


def get_adapter(provider: str):
    if provider not in PROVIDER_ADAPTERS:
        raise ValueError(
            f"No adapter for provider '{provider}'. "
            f"Known providers: {list(PROVIDER_ADAPTERS.keys())}. "
            f"Add a new adapter in providers.py to support more."
        )
    return PROVIDER_ADAPTERS[provider]
