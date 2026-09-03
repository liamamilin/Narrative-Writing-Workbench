"""Critic agent: material + instruction + WIR + draft -> validated critique.

Contract (docs/03 §4, docs/05): diagnoses, never rewrites. The
PASS/PATCH_REQUIRED decision is recomputed from the critique content using
the deterministic rule (docs/05 §7); the deterministic rule is authoritative
and any mismatch with the model's emitted decision is logged.
"""

from __future__ import annotations

import json

from .config import Config, DecisionThresholds
from .llm_client import LLMClient
from .models import StageResult
from .prompts import load_prompt
from .schemas import SchemaSet
from .structured import structured_call

QUALITY_DIMENSIONS = (
    "meaning_density",
    "progression",
    "immersion",
    "specificity",
    "restraint",
    "coherence",
)


def writing_quality(critique: dict) -> int:
    """WQ = M + P + I + S + R + C (docs/05 §2)."""
    quality = critique.get("quality", {}) or {}
    return sum(int(quality.get(dim, 0)) for dim in QUALITY_DIMENSIONS)


def severity_counts(critique: dict) -> dict[str, int]:
    counts = {"minor": 0, "moderate": 0, "major": 0, "fatal": 0}
    for issue in critique.get("issues", []) or []:
        sev = issue.get("severity")
        if sev in counts:
            counts[sev] += 1
    return counts


def compute_decision(critique: dict, thresholds: DecisionThresholds) -> tuple[str, dict]:
    """Deterministic decision rule (docs/05 §7).

    PASS iff fatal == 0 and major == 0 and moderate <= max_moderate_issues
    and WQ >= min_writing_quality.
    """
    counts = severity_counts(critique)
    wq = writing_quality(critique)
    passed = (
        counts["fatal"] == 0
        and counts["major"] == 0
        and counts["moderate"] <= thresholds.max_moderate_issues
        and wq >= thresholds.min_writing_quality
    )
    detail = {"severity_counts": counts, "wq": wq, "rule": {
        "max_moderate_issues": thresholds.max_moderate_issues,
        "min_writing_quality": thresholds.min_writing_quality,
    }}
    return ("PASS" if passed else "PATCH_REQUIRED"), detail


class CriticAgent:
    NAME = "critic"

    def __init__(self, client: LLMClient, config: Config, schemas: SchemaSet):
        self.client = client
        self.config = config
        self.schemas = schemas

    def system_prompt(self) -> str:
        return load_prompt(self.config.prompts_dir, self.NAME)

    def build_user_message(
        self,
        material: str,
        instruction: str,
        wir: dict,
        draft: str,
    ) -> str:
        th = self.config.thresholds
        return (
            "## Source Material\n\n"
            f"{material}\n\n"
            "## Writing Instruction\n\n"
            f"{instruction}\n\n"
            "## WIR\n\n"
            f"```json\n{json.dumps(wir, ensure_ascii=False, indent=1)}\n```\n\n"
            "## Draft\n\n"
            f"{draft}\n\n"
            "## Decision Thresholds (configurable)\n\n"
            f"PASS iff fatal=0 AND major=0 AND moderate<={th.max_moderate_issues} "
            f"AND WQ>={th.min_writing_quality} (WQ = sum of the six quality scores, max 30).\n\n"
            "## Required Output Schema (JSON Schema draft 2020-12)\n\n"
            f"```json\n{json.dumps(self.schemas.critique, ensure_ascii=False)}\n```\n\n"
            "Produce a schema-valid critique JSON object. Return JSON only."
        )

    def run(
        self,
        material: str,
        instruction: str,
        wir: dict,
        draft: str,
        on_delta=None,
    ) -> StageResult:
        stage = structured_call(
            self.client,
            role=self.NAME,
            role_cfg=self.config.role(self.NAME),
            system_prompt=self.system_prompt(),
            user_message=self.build_user_message(material, instruction, wir, draft),
            validator=self.schemas.validate_critique,
            on_delta=on_delta,
        )
        critique = stage.data
        model_decision = critique.get("decision")
        computed, detail = compute_decision(critique, self.config.thresholds)
        if model_decision != computed:
            warning = (
                f"critic decision '{model_decision}' contradicts deterministic rule "
                f"'{computed}' (counts={detail['severity_counts']}, WQ={detail['wq']}); "
                "deterministic rule applied"
            )
            stage.warnings.append(warning)
            critique["decision"] = computed
        stage.data = critique
        stage.decision_detail = detail  # type: ignore[attr-defined]
        return stage
