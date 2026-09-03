"""Shared structured-output call flow: generate -> parse -> validate -> one repair.

Failure handling per docs/01 §7:
1. one structured-output repair call;
2. never guess missing fields;
3. raise StructuredOutputError on second failure (caller marks run failed
   and persists raw output + validation errors).
"""

from __future__ import annotations

import logging

from .llm_client import LLMClient, GenerationResult
from .config import RoleConfig
from .models import StageResult, StructuredOutputError, Usage
from .utils import parse_json_output

logger = logging.getLogger(__name__)


def _usage_of(result: GenerationResult) -> Usage:
    return Usage(
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        latency_seconds=result.latency_seconds,
    )


def _parse_and_validate(text: str, validator) -> tuple[object | None, list[str]]:
    try:
        obj = parse_json_output(text)
    except ValueError as exc:
        return None, [str(exc)]
    errors = validator(obj)
    return obj, errors


def _generate(client: LLMClient, messages: list[dict[str, str]], *, role: str,
              role_cfg: RoleConfig, on_delta) -> GenerationResult:
    if on_delta is None:
        return client.generate_structured(messages, role=role, role_cfg=role_cfg)
    return client.generate_structured(messages, role=role, role_cfg=role_cfg,
                                      on_delta=on_delta)


def structured_call(
    client: LLMClient,
    *,
    role: str,
    role_cfg: RoleConfig,
    system_prompt: str,
    user_message: str,
    validator,
    on_delta=None,
) -> StageResult:
    """Run one structured generation with at most one repair attempt."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    result = _generate(client, messages, role=role, role_cfg=role_cfg,
                       on_delta=on_delta)
    usage = _usage_of(result)
    obj, errors = _parse_and_validate(result.text, validator)
    if not errors:
        return StageResult(data=obj, raw=result.text, usage=usage)

    logger.warning("%s: invalid structured output (%d errors); attempting repair", role, len(errors))

    if on_delta is not None:
        # Same protocol as language.write_with_language_repair: announce the
        # repair attempt with a reset so debug panes don't show two JSONs
        # concatenated. Tolerate single-arg callbacks (plain sinks).
        try:
            on_delta("", reset=True)
        except TypeError:
            on_delta("")

    repair_messages = messages + [
        {"role": "assistant", "content": result.text},
        {
            "role": "user",
            "content": (
                "Your previous output failed schema validation.\n"
                "Validation errors:\n- " + "\n- ".join(errors) + "\n\n"
                "Return the COMPLETE corrected JSON object only. "
                "Do not omit required fields, do not add fields outside the schema, "
                "do not explain."
            ),
        },
    ]
    repair_result = _generate(client, repair_messages, role=role,
                              role_cfg=role_cfg, on_delta=on_delta)
    usage = usage.add(_usage_of(repair_result))
    obj2, errors2 = _parse_and_validate(repair_result.text, validator)
    if not errors2:
        return StageResult(data=obj2, raw=repair_result.text, usage=usage, repair_used=True)

    raise StructuredOutputError(stage=role, raw=repair_result.text, errors=errors2)
