"""Data models shared across stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    latency_seconds: float = 0.0

    def add(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            estimated_cost=self.estimated_cost + other.estimated_cost,
            latency_seconds=self.latency_seconds + other.latency_seconds,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost": self.estimated_cost,
            "latency_seconds": self.latency_seconds,
        }


@dataclass
class StageResult:
    """Output of one agent stage."""

    data: Any  # parsed WIR / critique dict, or prose text
    raw: str  # last raw model output
    usage: Usage
    repair_used: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    run_id: str
    status: str  # success | failed
    final_text: str | None
    wir: dict | None
    draft: str | None
    critique: dict | None
    patched: bool
    usage: Usage
    errors: list[str] = field(default_factory=list)
    run_dir: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "success"


class StructuredOutputError(Exception):
    """Raised when a structured stage output remains invalid after one repair."""

    def __init__(self, stage: str, raw: str, errors: list[str]):
        super().__init__(f"{stage}: invalid structured output after repair: {errors}")
        self.stage = stage
        self.raw = raw
        self.errors = errors
