"""Provider-neutral LLM client abstraction.

Business logic depends only on ``LLMClient``. Concrete providers are pluggable.
No agent module imports a provider SDK.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .config import Config, RoleConfig
from .utils import parse_json_output  # noqa: F401 (re-export convenience)

logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_seconds: float = 0.0


class LLMClient(ABC):
    """Common interface for all model providers."""

    @abstractmethod
    def generate_text(
        self,
        messages: list[dict[str, str]],
        *,
        role: str,
        role_cfg: RoleConfig,
        on_delta=None,
    ) -> GenerationResult:
        """Free-form text generation.

        ``on_delta(delta: str)`` receives incremental text while generating
        (transport only; the returned GenerationResult is unchanged).
        """

    @abstractmethod
    def generate_structured(
        self,
        messages: list[dict[str, str]],
        *,
        role: str,
        role_cfg: RoleConfig,
        on_delta=None,
    ) -> GenerationResult:
        """Generation constrained to a single JSON object.

        Callers must still validate the parsed JSON against their schema;
        the provider constraint is best-effort, validation is authoritative.

        ``on_delta(delta: str)`` streams raw tokens while generating
        (transport only; validation semantics unchanged).
        """


class OpenAIClient(LLMClient):
    """OpenAI-compatible provider (works with OpenAI, Azure-style gateways and
    local servers exposing the OpenAI chat-completions API)."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 max_retries: int = 3):
        from openai import OpenAI  # imported lazily; keeps MockClient dependency-free

        self._client = OpenAI(api_key=api_key, base_url=base_url or None,
                              max_retries=max_retries)

    def _create(
        self,
        messages: list[dict[str, str]],
        role_cfg: RoleConfig,
        json_mode: bool,
        stream: bool = False,
    ):
        kwargs: dict[str, Any] = dict(
            model=role_cfg.model,
            messages=messages,
            temperature=role_cfg.temperature,
            max_tokens=role_cfg.max_output_tokens,
            timeout=role_cfg.timeout_seconds,
        )
        if stream:
            kwargs["stream"] = True
        if getattr(role_cfg, "reasoning_effort", ""):
            kwargs["extra_body"] = {"reasoning_effort": role_cfg.reasoning_effort}
        mode = role_cfg.structured_mode
        if json_mode and mode in ("auto", "json_object"):
            kwargs["response_format"] = {"type": "json_object"}
        try:
            return self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            from openai import APIStatusError

            # Only fall back on provider-side rejection of optional params
            # (4xx/5xx). Never swallow transport errors or assertion bugs.
            if not isinstance(exc, APIStatusError):
                raise
            dropped = False
            # While streaming, do NOT silently drop the JSON constraint: a
            # stream+response_format rejection must propagate so
            # generate_structured can fall back to non-streaming JSON mode.
            if (json_mode and mode == "auto" and "response_format" in kwargs
                    and not stream):
                kwargs.pop("response_format")
                dropped = True
            if "extra_body" in kwargs:
                kwargs.pop("extra_body")
                dropped = True
            if dropped:
                return self._client.chat.completions.create(**kwargs)
            raise

    @staticmethod
    def _to_result(resp, role_cfg: RoleConfig, latency: float) -> GenerationResult:
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        return GenerationResult(
            text=text,
            model=role_cfg.model,
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            latency_seconds=latency,
        )

    def generate_text(self, messages, *, role: str, role_cfg: RoleConfig,
                      on_delta=None) -> GenerationResult:
        start = time.monotonic()
        if on_delta is None:
            resp = self._create(messages, role_cfg, json_mode=False)
            return self._to_result(resp, role_cfg, time.monotonic() - start)
        resp = self._create(messages, role_cfg, json_mode=False, stream=True)
        parts: list[str] = []
        for chunk in resp:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            piece = (getattr(choices[0].delta, "content", None) or "")
            if piece:
                parts.append(piece)
                on_delta(piece)
        return GenerationResult(
            text="".join(parts), model=role_cfg.model,
            latency_seconds=time.monotonic() - start)

    def generate_structured(
        self, messages, *, role: str, role_cfg: RoleConfig, on_delta=None
    ) -> GenerationResult:
        start = time.monotonic()
        if on_delta is None:
            resp = self._create(messages, role_cfg, json_mode=True)
            return self._to_result(resp, role_cfg, time.monotonic() - start)
        from openai import APIStatusError

        try:
            resp = self._create(messages, role_cfg, json_mode=True, stream=True)
        except APIStatusError:
            # Provider rejected stream + JSON constraint combination.
            result = self._create(messages, role_cfg, json_mode=True)
            out = self._to_result(result, role_cfg, time.monotonic() - start)
            if out.text:
                on_delta(out.text)
            return out
        parts: list[str] = []
        for chunk in resp:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            piece = (getattr(choices[0].delta, "content", None) or "")
            if piece:
                parts.append(piece)
                on_delta(piece)
        return GenerationResult(
            text="".join(parts), model=role_cfg.model,
            latency_seconds=time.monotonic() - start)


class MockClient(LLMClient):
    """Deterministic scripted client for tests and dry runs.

    Responses are queued per role name (e.g. "architect", "writer", "critic",
    "patcher", "baseline", "judge"). Every call is recorded in ``self.calls``.
    """

    def __init__(self, responses: dict[str, list[str]] | None = None, model: str = "mock"):
        self._queues: dict[str, list[str]] = {k: list(v) for k, v in (responses or {}).items()}
        self._model = model
        self.calls: list[dict[str, Any]] = []

    def queue(self, role: str) -> list[str]:
        return self._queues.setdefault(role, [])

    def _next(self, role: str, kind: str, messages: list[dict[str, str]],
              role_cfg=None) -> GenerationResult:
        self.calls.append({"role": role, "kind": kind, "messages": messages,
                           "role_cfg": role_cfg})
        q = self.queue(role)
        if not q:
            raise AssertionError(f"MockClient has no queued response for role '{role}'")
        text = q.pop(0)
        in_tokens = sum(len(m.get("content", "")) for m in messages) // 4
        return GenerationResult(
            text=text,
            model=self._model,
            input_tokens=in_tokens,
            output_tokens=len(text) // 4,
            latency_seconds=0.001,
        )

    def generate_text(self, messages, *, role: str, role_cfg: RoleConfig,
                      on_delta=None) -> GenerationResult:
        result = self._next(role, "text", messages, role_cfg)
        if on_delta is not None and result.text:
            for i in range(0, len(result.text), 24):
                on_delta(result.text[i:i + 24])
        return result

    def generate_structured(
        self, messages, *, role: str, role_cfg: RoleConfig, on_delta=None
    ) -> GenerationResult:
        result = self._next(role, "structured", messages, role_cfg)
        if on_delta is not None and result.text:
            for i in range(0, len(result.text), 24):
                on_delta(result.text[i:i + 24])
        return result


def build_client(config: Config) -> LLMClient:
    """Instantiate the configured provider."""
    if config.provider == "mock":
        return MockClient()
    if config.provider == "openai":
        return OpenAIClient(api_key=config.api_key, base_url=config.base_url)
    raise ValueError(f"unknown provider: {config.provider}")
