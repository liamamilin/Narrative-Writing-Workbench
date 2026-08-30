"""Outline Architect agent (A1 baseline, docs/14 §4).

Produces a conventional writing outline: thesis, ordered sections, ending.
Deliberately NO reader-state modeling; validated against outline.schema.json
(additionalProperties: false enforces the boundary).
"""

from __future__ import annotations

import json

from .config import Config
from .llm_client import LLMClient
from .models import StageResult
from .prompts import load_prompt
from .schemas import SchemaSet
from .structured import structured_call


class OutlineArchitectAgent:
    NAME = "outline_architect"

    def __init__(self, client: LLMClient, config: Config, schemas: SchemaSet):
        self.client = client
        self.config = config
        self.schemas = schemas

    def system_prompt(self) -> str:
        return load_prompt(self.config.prompts_dir, "outline_architect")

    def build_user_message(
        self, material: str, instruction: str, task_type: str
    ) -> str:
        return (
            "## Source Material\n\n"
            f"{material}\n\n"
            "## Writing Instruction\n\n"
            f"{instruction}\n\n"
            "## Task Constraints\n\n"
            f"task_type: {task_type}\n\n"
            "## Required Output Schema (JSON Schema draft 2020-12)\n\n"
            f"```json\n{json.dumps(self.schemas.outline, ensure_ascii=False)}\n```\n\n"
            "Produce a schema-valid outline JSON object. Return JSON only."
        )

    def run(
        self, material: str, instruction: str, task_type: str
    ) -> StageResult:
        # Controlled generation settings: reuse the architect role config so
        # architecture, not model strength, is the changing variable (docs/14 §3).
        return structured_call(
            self.client,
            role=self.NAME,
            role_cfg=self.config.role("architect"),
            system_prompt=self.system_prompt(),
            user_message=self.build_user_message(material, instruction, task_type),
            validator=self.schemas.validate_outline,
        )
