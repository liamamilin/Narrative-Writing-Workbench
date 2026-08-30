"""RealWritingEngine — adapts the Narrative Writing Harness (app/) to the
Workbench product interface. Engine internals stay behind this class.

  generate : Architect -> WIR -> Writer -> language repair -> fidelity gate
  review   : Critic -> product-safe summary + positioned issues
  patch    : Patcher on a selection (lock-aware, fail-safe)
  map      : WIR beats -> paragraph ranges (read-only)
"""

from __future__ import annotations

import json
import os

from app.config import Config
from app.gates import hard_gates, resolve_expected_language
from app.language import write_with_language_repair
from app.llm_client import build_client
from app.models import StructuredOutputError
from app.schemas import SchemaSet
from app.structured import structured_call
from ..meaning_schema import MEANING_SCHEMA, validate_meaning, meaning_to_wir_block
from . import (DiscoveryFailed, GenerationFailed, GenerateResult,
               LockConflict, map_beats_to_paragraphs, split_paragraphs)

_TASK_TYPE_MAP = {
    "fiction_scene": "narrative_commentary",
    "narrative_analysis": "narrative_commentary",
    "character_analysis": "narrative_commentary",
    "essay": "narrative_commentary",
    "emotional_retelling": "narrative_commentary",
    "free_writing": "narrative_commentary",
}


def _extract_json(text: str) -> dict:
    for candidate in (text, text.strip()):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            raise ValueError("no valid JSON object in model output")
    raise ValueError("no JSON object in model output")


class RealWritingEngine:
    name = "real"

    def __init__(self, config_path: str | None = None):
        if config_path is None:
            config_path = os.environ.get("WORKBENCH_CONFIG")
        if config_path is None:
            from app.config import REPO_ROOT
            live = REPO_ROOT / "config.live.yaml"
            config_path = str(live) if live.exists() else None
        self.config = Config.load(config_path) if config_path else Config.default()
        self._apply_settings()
        self.client = build_client(self.config)
        self.schemas = SchemaSet(self.config.schemas_dir)
        from app.architect import ArchitectAgent
        from app.critic import CriticAgent
        from app.patcher import PatcherAgent
        from app.writer import WriterAgent
        self.architect = ArchitectAgent(self.client, self.config, self.schemas)
        self.writer = WriterAgent(self.client, self.config)
        self.critic = CriticAgent(self.client, self.config, self.schemas)
        self.patcher = PatcherAgent(self.client, self.config)

    def _apply_settings(self):
        """Overlay user Settings (model/timeout/temperature) onto the engine config."""
        from ..settings import load
        s = load()
        model = s.get("model")
        timeout = s.get("timeout_seconds")
        writer_temp = s.get("writer_temperature")
        for name, role in self.config.roles.items():
            if model:
                role.model = model
            if timeout:
                role.timeout_seconds = float(timeout)
            if writer_temp is not None and name == "writer":
                role.temperature = float(writer_temp)

    # ----------------------------------------------------------- generate ----

    def discover_meaning(self, *, topic, writing_mode, angle_mode,
                         custom_angle, avoid, config, emit=None) -> dict:
        if emit:
            emit("stage", {"stage": "discovery"})
        sys_prompt = _load_prompt(self.config.prompts_dir, "meaning_discovery")
        user = (
            f"## Topic\n\n{topic}\n\n"
            f"## Writing mode\n\n{writing_mode}\n\n"
            f"## Angle mode\n\n{angle_mode}\n"
        )
        if angle_mode == "custom" and custom_angle:
            user += f"\nUser-provided angle (refine, do not overwrite):\n{custom_angle}\n"
        if avoid:
            user += "\n## Avoid (already-tried angles; propose genuinely different ones)\n\n"
            user += "\n".join(f"- {a}" for a in avoid) + "\n"
        user += (
            "\n## Required Output Schema (JSON Schema draft 2020-12)\n\n"
            f"```json\n{json.dumps(MEANING_SCHEMA, ensure_ascii=False)}\n```\n\n"
            "Produce a schema-valid Meaning Discovery JSON object. Return JSON only."
        )
        try:
            stage = structured_call(
                self.client, role="meaning_discovery",
                role_cfg=self.config.role("architect"),
                system_prompt=sys_prompt, user_message=user,
                validator=validate_meaning)
        except StructuredOutputError as exc:
            raise DiscoveryFailed(
                "We couldn't find a strong angle. Please retry.") from exc
        return stage.data

    def generate(self, *, material, instruction, task_type, config,
                 meaning=None, emit=None, on_delta=None) -> GenerateResult:
        expected = resolve_expected_language(
            {"expected_language": config.get("expected_language"),
             "instruction": instruction, "material": material},
            self.config.expected_language)
        constraints = {
            "factual_fidelity": bool(config.get("locks", {}).get("facts", True))
                                and not meaning,
            "allow_new_facts": bool(meaning) or not bool(
                config.get("locks", {}).get("facts", True)),
            "target_length": config.get("target_length"),
        }
        if meaning:
            instruction = _compose_topic_instruction(instruction, meaning)
        engine_type = _TASK_TYPE_MAP.get(task_type, "narrative_commentary")
        if emit:
            emit("stage", {"stage": "structure"})
        try:
            arch = self.architect.run(material, instruction, engine_type, constraints)
        except StructuredOutputError as exc:
            raise GenerationFailed("The draft could not be generated correctly.") from exc
        wir = arch.data
        if meaning:
            wir.setdefault("task", {})["meaning"] = meaning_to_wir_block(meaning)
        target = config.get("target_length")
        if emit:
            emit("stage", {"stage": "writing"})
        lw = write_with_language_repair(
            self.writer, material=material, instruction=instruction,
            structure=wir, expected_language=expected, target_length=target,
            on_delta=on_delta)
        if lw.functional_failure or not (lw.text or "").strip():
            raise GenerationFailed("The draft could not be generated correctly.")
        gate = hard_gates(lw.text, {"material": material, "instruction": instruction,
                                    "target_length": target, "expected_language": expected})
        if gate["functional_failure"]:
            raise GenerationFailed("The draft did not pass a safety check. Please retry.")
        return GenerateResult(text=lw.text, plan={"wir": wir, "meaning": meaning})

    # -------------------------------------------------------------- review ----

    def review(self, *, content, material, instruction, plan, config) -> dict:
        wir = (plan or {}).get("wir") or self._minimal_wir(material, instruction, config)
        stage = self.critic.run(material, instruction, wir, content)
        critique = stage.data
        q = critique.get("quality", {})
        summary = {
            "progression": _label(q.get("progression")),
            "meaning_density": _label(q.get("meaning_density")),
            "immersion": _label(q.get("immersion")),
            "restraint": _label(q.get("restraint")),
            "coherence": _label(q.get("coherence")),
        }
        beat_map = {b["id"]: r for b, r in
                    zip(wir.get("beats", []), map_beats_to_paragraphs(wir.get("beats", []), content))}
        issues = []
        for i, issue in enumerate(critique.get("issues", []), 1):
            loc = str(issue.get("location", ""))
            para = _locate_paragraph(loc, beat_map, content)
            issues.append({
                "id": f"issue_{i}", "location": para,
                "type": (issue.get("diagnosis") or {}).get("type", "issue"),
                "message": (issue.get("diagnosis") or {}).get("description", ""),
                "fixable": True,
            })
        return {"summary": summary, "issues": issues}

    # --------------------------------------------------------------- patch ----

    def patch(self, *, content, before_text, instruction, locks, config) -> str:
        sys_prompt = _load_product_patch_prompt(self.config.prompts_dir)
        user = (
            "## Full draft (context only; you revise the selected passage)\n\n"
            f"{content}\n\n"
            "## Selected passage (rewrite ONLY this)\n\n"
            f"{before_text}\n\n"
            "## Revision instruction\n\n"
            f"{instruction}\n\n"
            "## Active locks\n\n"
            f"{json.dumps({k: v for k, v in locks.items() if v}, ensure_ascii=False)}\n\n"
            'Reply with ONLY a JSON object: {"after_text": "..."} or '
            '{"lock_conflict": true, "message": "..."}.'
        )
        role_cfg = self.config.role("writer")
        result = self.client.generate_text(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": user}],
            role="writer", role_cfg=role_cfg)
        try:
            data = _extract_json(result.text)
        except ValueError as exc:
            raise GenerationFailed("The revision could not be generated. Please retry.") from exc
        if data.get("lock_conflict"):
            raise LockConflict(data.get("message") or "This revision conflicts with an active lock.")
        after = data.get("after_text")
        if not isinstance(after, str) or not after.strip():
            raise GenerationFailed("The revision could not be generated. Please retry.")
        return after

    # -------------------------------------------------------- writing map ----

    def writing_map(self, *, plan, content) -> list[dict]:
        beats = ((plan or {}).get("wir") or {}).get("beats", [])
        return map_beats_to_paragraphs(beats, content)

    # --------------------------------------------------------------- util ----

    def _minimal_wir(self, material, instruction, config) -> dict:
        return {"beats": [], "task": {"type": "narrative_commentary",
                                      "objective": instruction}}


def _label(score):
    if score is None:
        return "good"
    return "strong" if score >= 4 else ("good" if score == 3 else "needs_attention")


def _locate_paragraph(location: str, beat_map: dict, content: str) -> dict:
    for bid, rng in beat_map.items():
        if bid and bid in location and rng.get("paragraph_start"):
            return {"paragraph_start": rng["paragraph_start"],
                    "paragraph_end": rng["paragraph_end"]}
    n = len(split_paragraphs(content))
    return {"paragraph_start": 1, "paragraph_end": max(1, n)}


def _load_product_patch_prompt(prompts_dir):
    return _load_prompt(prompts_dir, "product_patch")


def _load_prompt(prompts_dir, name):
    from app.prompts import load_prompt
    return load_prompt(prompts_dir, name)


def _compose_topic_instruction(instruction: str, meaning: dict) -> str:
    """Feed the selected meaning explicitly into the WIR stage (product/13 §Output to WIR)."""
    block = meaning_to_wir_block(meaning)
    lines = ["## Meaning to develop (do not replace this thesis)", ""]
    lines.append(f"Selected angle: {block['selected_angle']}")
    lines.append(f"Core question: {block['core_question']}")
    lines.append(f"Deep meaning: {block['deep_meaning']}")
    lines.append(f"Reader should end understanding: {block['reader_end_state']}")
    if block["key_tensions"]:
        lines.append("Key tensions: " + "; ".join(block["key_tensions"]))
    lines += ["", "This piece is topic-led (not source-grounded). Do not invent "
                  "citations or claim unsupported authority.", ""]
    if instruction:
        lines.append("## Writer's own note")
        lines.append(instruction)
    return "\n".join(lines)
