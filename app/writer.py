"""Writer agent: material + instruction + WIR -> prose only.

Contract (docs/03 §3): renders WIR faithfully; never redesigns it.

V1.2 (docs/17): the user message carries an explicit OUTPUT LANGUAGE
directive and, when configured, an Output Budget directive. Both are
functional-fidelity instructions, not writing-policy changes.
"""

from __future__ import annotations

import json

from .config import Config
from .llm_client import LLMClient
from .models import StageResult, Usage
from .prompts import load_prompt

LANGUAGE_NAMES = {"zh": "Chinese", "en": "English"}


class WriterAgent:
    NAME = "writer"

    def __init__(self, client: LLMClient, config: Config, prompt_file: str = "writer"):
        self.client = client
        self.config = config
        # prompt_file selects the system prompt (writer | writer_gi | writer_outline).
        # Generation settings stay pinned to the "writer" role for all variants
        # so architecture, not model strength, is the changing variable (docs/14 §3).
        self.prompt_file = prompt_file

    def system_prompt(self) -> str:
        return load_prompt(self.config.prompts_dir, self.prompt_file)

    def build_user_message(
        self,
        material: str,
        instruction: str,
        wir: dict,
        structure_label: str = "WIR (validated; immutable input)",
        expected_language: str | None = None,
        target_length: int | None = None,
        extra_directive: str = "",
    ) -> str:
        parts = [
            "## Source Material\n\n"
            f"{material}\n\n"
            "## Writing Instruction\n\n"
            f"{instruction}\n\n"
            f"## {structure_label}\n\n"
            f"```json\n{json.dumps(wir, ensure_ascii=False, indent=1)}\n```",
        ]
        if expected_language in LANGUAGE_NAMES:
            name = LANGUAGE_NAMES[expected_language]
            parts.append(
                "## Output Language\n\n"
                f"OUTPUT LANGUAGE: {name}\n\n"
                f"Write the complete final prose in {name}. "
                f"Do not switch to English even if internal representations, "
                "examples, schemas, or model reasoning contain English. "
                "Never mix languages in the prose."
            )
        if target_length:
            parts.append(
                "## Output Budget\n\n"
                f"Target length: about {target_length} characters in total. "
                "Not every structural unit deserves a full paragraph: weigh "
                "Meaning Gain against Word Cost. Units marked core may "
                "receive substantial prose; support units get brief "
                "development; bridge units get minimal prose and may be "
                "merged into an adjacent paragraph."
            )
        parts.append("Write the prose now. Return prose text only.")
        if extra_directive:
            parts.append(extra_directive)
        return "\n\n".join(parts)

    def run(
        self,
        material: str,
        instruction: str,
        wir: dict,
        structure_label: str = "WIR (validated; immutable input)",
        expected_language: str | None = None,
        target_length: int | None = None,
        extra_directive: str = "",
        on_delta=None,
    ) -> StageResult:
        messages = [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": self.build_user_message(
                material, instruction, wir, structure_label,
                expected_language=expected_language,
                target_length=target_length,
                extra_directive=extra_directive)},
        ]
        result = self.client.generate_text(
            messages, role=self.prompt_file, role_cfg=self.config.role("writer"),
            on_delta=on_delta,
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
