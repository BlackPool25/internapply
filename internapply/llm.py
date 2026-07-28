"""OpenCode Go LLM client wrapper.

Provides a reusable, logging-aware client for OpenAI-compatible LLM APIs
with retry logic, error handling, and convenience methods for structured
output.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any

import openai
from loguru import logger

from internapply.config import get_config

# ── Retry constants ───────────────────────────────────────────────────
_MAX_RETRIES = 3
_BASE_DELAY_S = 2.0
_MAX_DELAY_S = 30.0


def _exponential_backoff(attempt: int) -> float:
    """Return sleep seconds for *attempt* (0-indexed) with jitter."""
    delay = min(_BASE_DELAY_S * (2 ** attempt), _MAX_DELAY_S)
    jitter = random.uniform(0, 0.5 * delay)
    return delay + jitter


def _truncate(text: str, max_len: int = 512) -> str:
    """Truncate *text* to *max_len* characters for log messages."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"… [{len(text) - max_len} more chars]"


def _build_client(api_key: str | None, base_url: str | None) -> openai.OpenAI:
    """Create a synchronous OpenAI client pointing at the OpenCode Go API."""
    cfg = get_config()
    resolved_key = api_key or cfg.OPENCODE_GO_API_KEY
    resolved_url = base_url or cfg.OPENCODE_GO_BASE_URL

    if not resolved_key:
        raise ValueError(
            "OPENCODE_GO_API_KEY is not set. "
            "Provide it via the constructor, environment variable, or .env file."
        )

    return openai.OpenAI(api_key=resolved_key, base_url=resolved_url)


def _build_async_client(api_key: str | None, base_url: str | None) -> openai.AsyncOpenAI:
    """Create an asynchronous OpenAI client pointing at the OpenCode Go API."""
    cfg = get_config()
    resolved_key = api_key or cfg.OPENCODE_GO_API_KEY
    resolved_url = base_url or cfg.OPENCODE_GO_BASE_URL

    if not resolved_key:
        raise ValueError(
            "OPENCODE_GO_API_KEY is not set. "
            "Provide it via the constructor, environment variable, or .env file."
        )

    return openai.AsyncOpenAI(api_key=resolved_key, base_url=resolved_url)


class LLMClient:
    """Wraps the OpenAI-compatible OpenCode Go API with retry & logging.

    Usage::

        from internapply.llm import LLMClient

        client = LLMClient()
        reply = client.complete([{"role": "user", "content": "Hello"}])
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        cfg = get_config()
        self.api_key: str = api_key or cfg.OPENCODE_GO_API_KEY
        self.model: str = model or cfg.OPENCODE_GO_MODEL
        self.base_url: str = base_url or cfg.OPENCODE_GO_BASE_URL

        # Create the reusable synchronous client (lazily — not at import).
        self._sync_client: openai.OpenAI | None = None
        self._async_client: openai.AsyncOpenAI | None = None

    # ── Client properties (lazy-init) ────────────────────────────────

    @property
    def client(self) -> openai.OpenAI:
        """Lazily-initialised synchronous OpenAI client."""
        if self._sync_client is None:
            self._sync_client = _build_client(self.api_key, self.base_url)
        return self._sync_client

    @property
    def async_client(self) -> openai.AsyncOpenAI:
        """Lazily-initialised asynchronous OpenAI client."""
        if self._async_client is None:
            self._async_client = _build_async_client(self.api_key, self.base_url)
        return self._async_client

    # ── Public sync methods ──────────────────────────────────────────

    def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        response_format: dict | None = None,
    ) -> str:
        """Send a chat completion request and return the response text.

        Parameters
        ----------
        messages:
            Chat messages in OpenAI format
            (e.g. ``[{"role": "user", "content": "…"}]``).
        model:
            Override the default model for this call.
        max_tokens:
            Maximum number of tokens in the response.
        temperature:
            Sampling temperature (default 0.3 for structured resume tasks).
        response_format:
            Optional response format specification
            (e.g. ``{"type": "json_object"}``).

        Returns
        -------
        The response content string.
        """
        resolved_model = model or self.model
        kwargs: dict[str, Any] = {}
        if response_format is not None:
            kwargs["response_format"] = response_format
        logger.debug(
            "LLM request — model={} messages={} max_tokens={} temperature={} kwargs={}",
            resolved_model,
            _truncate(json.dumps(messages), 256),
            max_tokens,
            temperature,
            kwargs,
        )

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = self.client.chat.completions.create(
                    model=resolved_model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )
                text = response.choices[0].message.content or ""
                logger.debug(
                    "LLM response — model={} tokens={} text={}",
                    resolved_model,
                    _tokens_info(response),
                    _truncate(text),
                )
                return text

            except openai.AuthenticationError as exc:
                logger.error(
                    "Authentication failed (attempt {}/{}): {}",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                )
                raise

            except openai.RateLimitError as exc:
                delay = _exponential_backoff(attempt)
                logger.warning(
                    "Rate limited (attempt {}/{}). Retrying in {:.1f}s — {}",
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    exc,
                )
                time.sleep(delay)
                last_exc = exc

            except openai.APITimeoutError as exc:
                delay = _exponential_backoff(attempt)
                logger.warning(
                    "API timeout (attempt {}/{}). Retrying in {:.1f}s — {}",
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    exc,
                )
                time.sleep(delay)
                last_exc = exc

            except openai.APIConnectionError as exc:
                delay = _exponential_backoff(attempt)
                logger.warning(
                    "API connection error (attempt {}/{}). Retrying in {:.1f}s — {}",
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    exc,
                )
                time.sleep(delay)
                last_exc = exc

            except openai.APIError as exc:
                delay = _exponential_backoff(attempt)
                logger.warning(
                    "API error (attempt {}/{}). Retrying in {:.1f}s — {}",
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    exc,
                )
                time.sleep(delay)
                last_exc = exc

        # All retries exhausted
        msg = f"LLM request failed after {_MAX_RETRIES} retries"
        logger.error(msg)
        raise RuntimeError(msg) from last_exc

    def complete_json(
        self,
        messages: list[dict],
        model: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion and parse the response as JSON.

        Tries to use the ``response_format={"type": "json_object"}``
        parameter.  If the model does not support it (i.e. the API ignores
        it), falls back to parsing the raw text with ``json.loads()``.

        Returns
        -------
        Parsed JSON dictionary.
        """
        resolved_model = model or self.model
        text = self.complete(
            messages=messages,
            model=model,
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        # Attempt JSON parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(
                "response_format=json_object not honoured by model {}; "
                "falling back to unstructured JSON parse",
                resolved_model,
            )
            # Fallback: call complete without response_format and parse
            return self._json_from_text(messages, model)

    def validate_connection(self) -> bool:
        """Verify the API key and endpoint with a minimal request.

        Sends a short prompt (``"Return OK"``) and checks for a
        successful response.

        Returns
        -------
        ``True`` if the API responded successfully, ``False`` otherwise.
        """
        try:
            _ = self.complete(
                messages=[{"role": "user", "content": "Return OK"}],
                max_tokens=16,
                temperature=0,
            )
            logger.info("LLM connection validated — API key is active")
            return True
        except openai.AuthenticationError as exc:
            logger.error("LLM connection failed — invalid API key: {}", exc)
        except openai.APIConnectionError as exc:
            logger.error("LLM connection failed — cannot reach {}: {}", self.base_url, exc)
        except openai.RateLimitError as exc:
            logger.error("LLM connection failed — rate limited: {}", exc)
        except openai.APITimeoutError as exc:
            logger.error("LLM connection failed — timeout: {}", exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("LLM connection failed — unexpected error: {}", exc)
        return False

    # ── Public async methods ─────────────────────────────────────────

    async def async_complete(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        response_format: dict | None = None,
    ) -> str:
        """Async version of :meth:`complete`."""
        resolved_model = model or self.model
        kwargs: dict[str, Any] = {}
        if response_format is not None:
            kwargs["response_format"] = response_format
        logger.debug(
            "LLM request (async) — model={} messages={} max_tokens={} temperature={} kwargs={}",
            resolved_model,
            _truncate(json.dumps(messages), 256),
            max_tokens,
            temperature,
            kwargs,
        )

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self.async_client.chat.completions.create(
                    model=resolved_model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )
                text = response.choices[0].message.content or ""
                logger.debug(
                    "LLM response (async) — model={} tokens={} text={}",
                    resolved_model,
                    _tokens_info(response),
                    _truncate(text),
                )
                return text

            except openai.AuthenticationError as exc:
                logger.error(
                    "Authentication failed (async, attempt {}/{}): {}",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                )
                raise

            except openai.RateLimitError as exc:
                delay = _exponential_backoff(attempt)
                logger.warning(
                    "Rate limited (async, attempt {}/{}). Retrying in {:.1f}s — {}",
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                last_exc = exc

            except openai.APITimeoutError as exc:
                delay = _exponential_backoff(attempt)
                logger.warning(
                    "API timeout (async, attempt {}/{}). Retrying in {:.1f}s — {}",
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                last_exc = exc

            except openai.APIConnectionError as exc:
                delay = _exponential_backoff(attempt)
                logger.warning(
                    "API connection error (async, attempt {}/{}). Retrying in {:.1f}s — {}",
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                last_exc = exc

            except openai.APIError as exc:
                delay = _exponential_backoff(attempt)
                logger.warning(
                    "API error (async, attempt {}/{}). Retrying in {:.1f}s — {}",
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                last_exc = exc

        msg = f"LLM request (async) failed after {_MAX_RETRIES} retries"
        logger.error(msg)
        raise RuntimeError(msg) from last_exc

    async def async_complete_json(
        self,
        messages: list[dict],
        model: str | None = None,
    ) -> dict[str, Any]:
        """Async version of :meth:`complete_json`."""
        resolved_model = model or self.model
        text = await self.async_complete(
            messages=messages,
            model=model,
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(
                "response_format=json_object not honoured by model {} (async); "
                "falling back to unstructured JSON parse",
                resolved_model,
            )
            return await self._async_json_from_text(messages, model)

    # ── Internal helpers ─────────────────────────────────────────────

    def _json_from_text(self, messages: list[dict], model: str | None = None) -> dict[str, Any]:
        """Fallback: call complete() without response_format, parse JSON."""
        text = self.complete(
            messages=[
                *messages,
                {
                    "role": "system",
                    "content": "You MUST output ONLY valid JSON. No markdown, no explanation.",
                },
            ],
            model=model,
        )
        # Strip possible markdown fences
        cleaned = text.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (possibly with language hint)
            first_nl = cleaned.find("\n")
            cleaned = cleaned[first_nl + 1 :] if first_nl != -1 else cleaned
            # Remove closing fence
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
            elif "```" in cleaned:
                cleaned = cleaned[: cleaned.rindex("```")].strip()

        return json.loads(cleaned)

    async def _async_json_from_text(
        self,
        messages: list[dict],
        model: str | None = None,
    ) -> dict[str, Any]:
        """Fallback for async complete_json."""
        text = await self.async_complete(
            messages=[
                *messages,
                {
                    "role": "system",
                    "content": "You MUST output ONLY valid JSON. No markdown, no explanation.",
                },
            ],
            model=model,
        )
        cleaned = text.strip()
        if cleaned.startswith("```"):
            first_nl = cleaned.find("\n")
            cleaned = cleaned[first_nl + 1 :] if first_nl != -1 else cleaned
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
            elif "```" in cleaned:
                cleaned = cleaned[: cleaned.rindex("```")].strip()

        return json.loads(cleaned)


# ── Module-level helpers ──────────────────────────────────────────────


def _tokens_info(response: Any) -> str:
    """Extract a human-readable token-usage summary from a response."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return "n/a"
    parts = []
    if hasattr(usage, "prompt_tokens") and usage.prompt_tokens is not None:
        parts.append(f"in={usage.prompt_tokens}")
    if hasattr(usage, "completion_tokens") and usage.completion_tokens is not None:
        parts.append(f"out={usage.completion_tokens}")
    if hasattr(usage, "total_tokens") and usage.total_tokens is not None:
        parts.append(f"total={usage.total_tokens}")
    return " ".join(parts) if parts else "n/a"


__all__ = ["LLMClient"]
