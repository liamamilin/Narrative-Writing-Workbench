"""Patcher agent: one-pass minimal correction (docs/06 Patch Protocol).

Runs only when the Critic decision is PATCH_REQUIRED. Consumes the critique
preserve list and patch targets, returns the complete patched text.
Never calls the Critic recursively.
"""

from __future__ import annotations

import json

from .config import Config
from .llm_client import LLMClient
from .models import StageResult, Usage
from .prompts import load_prompt


class PatcherAgent:
    NAME = "patcher"

    def __init__(self, client: LLMClient, config: Config):
        self.client = client
        self.config = config

    def system_prompt(self) -> str:
        return load_prompt(self.config.prompts_dir, self.NAME)

    def build_user_message(
        self,
        material: str,
        instruction: str,
        wir: dict,
        draft: str,
        critique: dict,
    ) -> str:
        patch_input = {
            "decision": critique.get("decision"),
            "fidelity": critique.get("fidelity"),
            "issues": critique.get("issues"),
            "preserve": critique.get("preserve"),
            "patch_targets": critique.get("patch_targets"),
            "revision_strategy": critique.get("revision_strategy"),
        }
        return (
            "## Source Material\n\n"
            f"{material}\n\n"
            "## Writing Instruction\n\n"
            f"{instruction}\n\n"
            "## WIR\n\n"
            f"```json\n{json.dumps(wir, ensure_ascii=False, indent=1)}\n```\n\n"
            "## Draft\n\n"
            f"{draft}\n\n"
            "## Critique (apply these corrections; patch, do not rewrite)\n\n"
            f"```json\n{json.dumps(patch_input, ensure_ascii=False, indent=1)}\n```\n\n"
            "Return the COMPLETE patched text only."
        )

    def run(
        self,
        material: str,
        instruction: str,
        wir: dict,
        draft: str,
        critique: dict,
    ) -> StageResult:
        messages = [
            {"role": "system", "content": self.system_prompt()},
            {
                "role": "user",
                "content": self.build_user_message(material, instruction, wir, draft, critique),
            },
        ]
        result = self.client.generate_text(
            messages, role=self.NAME, role_cfg=self.config.role(self.NAME)
        )
        return StageResult(
            data=result.text.strip(),
            raw=result.text,
            usage=Usage(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_seconds=result.latency_seconds,
            ),
        )
