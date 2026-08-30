"""Writer-boundary language repair policy (docs/17 §3).

Language mismatch is a functional generation failure, not a prose-quality
problem. After every Writer generation we run the expected-language check
immediately; on mismatch we perform EXACTLY ONE repair/regeneration attempt
with the same material, instruction, structure and writer policy, explicitly
demanding the expected language. If the repair still fails, the sample is
marked functional_failure and must not proceed to the Critic or count as the
final Writer sample. The first failed generation is preserved, never silently
discarded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .gates import detect_language
from .models import Usage
from .writer import LANGUAGE_NAMES

REPAIR_DIRECTIVE_TEMPLATE = (
    "## Language Repair\n\n"
    "Your previous attempt was written in {got}, but the required "
    "OUTPUT LANGUAGE is {want}. Rewrite the complete final prose in {want}. "
    "Preserve the same meaning, structure and order of the previous attempt. "
    "Do not switch to English even if internal representations, examples, "
    "schemas, or model reasoning contain English."
)


@dataclass
class LanguageWriteResult:
    text: str | None
    attempts: int
    repaired: bool               # repair succeeded (attempt 2 used)
    functional_failure: bool     # language still wrong after one repair
    original_language: str
    final_language: str
    original_text: str | None = None   # first (mismatched) generation, preserved
    usage: Usage = field(default_factory=Usage)
    repair_used: bool = False

    def to_row_fields(self) -> dict[str, Any]:
        """Fields persisted on every benchmark output row (docs/17 §3)."""
        return {
            "language_attempts": self.attempts,
            "language_repaired": self.repaired,
            "language_functional_failure": self.functional_failure,
            "original_language": self.original_language,
            "final_language": self.final_language,
        }


def write_with_language_repair(
    writer,
    *,
    material: str,
    instruction: str,
    structure: dict,
    expected_language: str,
    structure_label: str = "WIR (validated; immutable input)",
    target_length: int | None = None,
    on_delta=None,
) -> LanguageWriteResult:
    """Generate prose, enforcing the one-repair language policy.

    Optional ``on_delta(delta: str, reset: bool)`` streams generated text;
    a repair attempt is announced with ``on_delta("", True)`` before it runs.
    """
    cb = (lambda d: on_delta(d, False)) if on_delta else None
    first = writer.run(
        material, instruction, structure, structure_label=structure_label,
        expected_language=expected_language, target_length=target_length,
        on_delta=cb,
    )
    lang1 = detect_language(first.data or "")
    usage = first.usage
    if lang1 == expected_language:
        return LanguageWriteResult(
            text=first.data, attempts=1, repaired=False,
            functional_failure=False,
            original_language=lang1, final_language=lang1,
            usage=usage, repair_used=first.repair_used,
        )
    want = LANGUAGE_NAMES.get(expected_language, expected_language)
    got = {"en": "English", "zh": "Chinese"}.get(lang1, lang1 or "empty")
    if on_delta:
        on_delta("", True)
    second = writer.run(
        material, instruction, structure, structure_label=structure_label,
        expected_language=expected_language, target_length=target_length,
        extra_directive=REPAIR_DIRECTIVE_TEMPLATE.format(got=got, want=want),
        on_delta=cb,
    )
    usage = usage.add(second.usage)
    lang2 = detect_language(second.data or "")
    ok = lang2 == expected_language
    return LanguageWriteResult(
        text=second.data, attempts=2, repaired=ok,
        functional_failure=not ok,
        original_language=lang1, final_language=lang2,
        original_text=first.data, usage=usage,
        repair_used=bool(first.repair_used or second.repair_used),
    )
