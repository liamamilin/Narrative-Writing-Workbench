"""Architect agent: material + instruction -> validated WIR.

Contract (docs/03 §2): designs meaning progression and reader-state
transitions; never writes prose; at most one repair attempt.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import Config
from .llm_client import LLMClient
from .models import StageResult
from .prompts import load_prompt
from .schemas import SchemaSet
from .structured import structured_call

DEFAULT_CONSTRAINTS = {
    "factual_fidelity": True,
    "allow_new_facts": False,
    "max_explicit_moralization": 0,
    "avoid_generic_philosophy": True,
    "avoid_emotional_labeling_when_behavior_suffices": True,
    "max_contrast_redefinition_patterns": 1,
    "target_length": None,
}


class ArchitectAgent:
    NAME = "architect"

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
        task_type: str,
        constraints: dict | None = None,
    ) -> str:
        merged = dict(DEFAULT_CONSTRAINTS)
        if constraints:
            merged.update(constraints)
        return (
            "## Source Material\n\n"
            f"{material}\n\n"
            "## Writing Instruction\n\n"
            f"{instruction}\n\n"
            "## Task Constraints\n\n"
            f"task_type: {task_type}\n"
            f"constraints: {json.dumps(merged, ensure_ascii=False)}\n\n"
            "## Required Output Schema (JSON Schema draft 2020-12)\n\n"
            f"```json\n{json.dumps(self.schemas.wir, ensure_ascii=False)}\n```\n\n"
            "Produce a schema-valid WIR JSON object. Return JSON only."
        )

    def run(
        self,
        material: str,
        instruction: str,
        task_type: str,
        constraints: dict | None = None,
        on_delta=None,
    ) -> StageResult:
        return structured_call(
            self.client,
            role=self.NAME,
            role_cfg=self.config.role(self.NAME),
            system_prompt=self.system_prompt(),
            user_message=self.build_user_message(material, instruction, task_type, constraints),
            validator=self.schemas.validate_wir,
            on_delta=on_delta,
        )
