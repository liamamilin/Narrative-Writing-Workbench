"""Engine adapter boundary (PRODUCT_IMPLEMENTATION_TASK: Engine Adapter).

Product code depends only on this protocol; engine internals (Architect,
WIR, Critic, Patcher) live behind RealWritingEngine and never leak into UI
objects. MockWritingEngine has the identical interface for tests/dev.
"""

from __future__ import annotations

from typing import Protocol


class EngineError(Exception):
    """Product-safe generation/patch failure. Message is user-displayable."""


class GenerationFailed(EngineError):
    retryable = True


class LockConflict(EngineError):
    """A requested revision cannot satisfy the active locks (fail safely)."""

    retryable = True


class DiscoveryFailed(EngineError):
    retryable = True


class EvidenceCheckFailed(EngineError):
    retryable = True


class ReaderPathReviewFailed(EngineError):
    retryable = True


class GenerateResult:
    def __init__(self, text: str, plan: dict):
        self.text = text
        self.plan = plan  # internal EnginePlan payload; never sent to UI raw


class WritingEngine(Protocol):
    name: str

    def discover_meaning(self, *, topic: str, writing_mode: str,
                         angle_mode: str, custom_angle: str,
                         avoid: list[str], config: dict,
                         emit=None, on_delta=None) -> dict: ...

    def generate(self, *, material: str, instruction: str, task_type: str,
                 config: dict, meaning: dict | None = None,
                 emit=None, on_delta=None,
                 on_struct_delta=None,
                 plan: dict | None = None,
                 on_plan=None) -> GenerateResult: ...

    def review(self, *, content: str, material: str, instruction: str,
               plan: dict | None, config: dict,
               on_delta=None) -> dict: ...

    def check_evidence(self, *, content: str,
                       sources: list[dict], on_delta=None) -> dict: ...

    def review_reader_path(self, *, content: str, on_delta=None) -> dict: ...

    def patch(self, *, content: str, before_text: str, instruction: str,
              locks: dict, config: dict) -> str: ...

    def writing_map(self, *, plan: dict | None, content: str) -> list[dict]: ...

    def suggest_instruction(self, *, material: str, topic: str,
                            task_type: str, instruction: str, config: dict,
                            language: str, meaning: dict | None = None,
                            avoid: list[str] | None = None) -> str: ...

    def suggest_topics(self, *, domain: str | None = None,
                       object_name: str | None = None,
                       tension: str | None = None,
                       avoid: list[str] | None = None,
                       config: dict | None = None) -> dict: ...


# --------------------------------------------------------------- helpers ----

def split_paragraphs(content: str) -> list[str]:
    return [p for p in content.split("\n\n") if p.strip()]


def map_beats_to_paragraphs(beats: list[dict], content: str) -> list[dict]:
    """Read-only WIR beat -> paragraph mapping (V0 heuristic, docs: 04 §4)."""
    paras = split_paragraphs(content)
    n, m = len(paras), max(1, len(beats))
    out = []
    for i, beat in enumerate(beats):
        start = i * n // m
        end = max(start, (i + 1) * n // m - 1)
        if i == m - 1:
            end = max(start, n - 1)
        out.append({
            "beat_id": beat.get("id", f"B{i + 1}"),
            "function": (beat.get("function") or {}).get("primary", ""),
            "reader_before": (beat.get("reader_transition") or {}).get("from", ""),
            "reader_after": (beat.get("reader_transition") or {}).get("to", ""),
            "meaning_gain": beat.get("meaning_gain", ""),
            "paragraph_start": start + 1 if paras else None,
            "paragraph_end": end + 1 if paras else None,
        })
    return out


def get_engine() -> WritingEngine:
    from ..settings import apply_env, engine_mode, load
    apply_env(load())
    if engine_mode() == "real":
        from .real import RealWritingEngine
        return RealWritingEngine()
    from .mock import MockWritingEngine
    return MockWritingEngine()
