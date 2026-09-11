"""RealWritingEngine — adapts the Narrative Writing Harness (app/) to the
Workbench product interface. Engine internals stay behind this class.

  generate : Architect -> WIR -> Writer -> language repair -> fidelity gate
  review   : Critic -> product-safe summary + positioned issues
  patch    : Patcher on a selection (lock-aware, fail-safe)
  map      : WIR beats -> paragraph ranges (read-only)
"""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("workbench.engine.real")

from app.config import Config
from app.gates import hard_gates, resolve_expected_language
from app.language import write_with_language_repair
from app.llm_client import build_client
from app.models import StructuredOutputError
from app.schemas import SchemaSet
from app.structured import structured_call
from ..meaning_schema import MEANING_SCHEMA, validate_meaning, meaning_to_wir_block
from ..topic_schema import validate_topics
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

# Bilingual hints for the Intent Coach (model-facing).
_TASK_DESCRIPTIONS = {
    "fiction_scene": "写一个具体场景的小说片段(场景、动作、对话)",
    "narrative_analysis": "分析故事的叙事机制:视角、信息释放、推进",
    "character_analysis": "剖析一个人物:行为、动机、矛盾",
    "essay": "观点性散文:论点要有推进与重量",
    "emotional_retelling": "带着情感重述一段事件/记忆",
    "free_writing": "放松随笔,结构约束最弱",
}

# Cap source material fed to the lightweight Intent Coach call.
_MATERIAL_CAP = 8000


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
                         custom_angle, avoid, config, emit=None,
                         on_delta=None) -> dict:
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
                validator=validate_meaning, on_delta=on_delta)
        except StructuredOutputError as exc:
            raise DiscoveryFailed(
                "We couldn't find a strong angle. Please retry.") from exc
        return stage.data

    def generate(self, *, material, instruction, task_type, config,
                 meaning=None, emit=None, on_delta=None,
                 on_struct_delta=None) -> GenerateResult:
        allow_new_facts = bool(meaning) or not bool(
            config.get("locks", {}).get("facts", True))
        expected = resolve_language_for(config, material, instruction,
                                        meaning, self.config.expected_language)
        constraints = {
            "factual_fidelity": bool(config.get("locks", {}).get("facts", True))
                                and not meaning,
            "allow_new_facts": allow_new_facts,
            "target_length": config.get("target_length"),
        }
        if meaning:
            instruction = _compose_topic_instruction(instruction, meaning)
        instruction = _dial_block(config) + (instruction or "")
        engine_type = _TASK_TYPE_MAP.get(task_type, "narrative_commentary")
        if emit:
            emit("stage", {"stage": "structure"})
        try:
            arch = self.architect.run(material, instruction, engine_type,
                                      constraints, on_delta=on_struct_delta)
        except StructuredOutputError as exc:
            raise GenerationFailed("The draft could not be generated correctly.") from exc
        wir = arch.data
        if emit:
            emit("stage_summary", {"stage": "structure",
                                   "text": _outline_summary(wir)})
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
                                    "target_length": target,
                                    "expected_language": expected,
                                    "allow_new_facts": allow_new_facts})
        if gate["functional_failure"]:
            log.warning("gate failure task=%s reasons=%s", task_type,
                        gate["failure_reasons"])
            raise GenerationFailed(
                f"草稿未通过安全检查:{_gate_message(gate['failure_reasons'])}。"
                "请调整意图或目标字数后重试。")
        return GenerateResult(text=lw.text, plan={"wir": wir, "meaning": meaning})

    # -------------------------------------------------------------- review ----

    def review(self, *, content, material, instruction, plan, config,
               on_delta=None) -> dict:
        wir = (plan or {}).get("wir") or self._minimal_wir(material, instruction, config)
        stage = self.critic.run(material, instruction, wir, content,
                                on_delta=on_delta)
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

    # ----------------------------------------------------- suggest intent ----

    def suggest_instruction(self, *, material, topic, task_type,
                            instruction, config, language,
                            meaning=None, avoid=None) -> str:
        """Draft/sharpen ONE writing-instruction (Intent) via the model."""
        sys_prompt = _load_prompt(self.config.prompts_dir, "suggest_instruction")
        type_label = _TASK_DESCRIPTIONS.get(task_type, task_type)
        parts = [f"## Task type\n\n{task_type} — {type_label}",
                 f"## Source material\n\n{material[:_MATERIAL_CAP] or '(none)'}"]
        if topic:
            parts.append(f"## Topic (idea-based)\n\n{topic}")
        if meaning:
            block = meaning_to_wir_block(meaning)
            parts.append(
                "## Selected angle / core question\n\n"
                f"Selected angle: {block['selected_angle']}\n"
                f"Core question: {block['core_question']}")
        instr = instruction or "(empty — draft from scratch)"
        parts.append(f"## Current instruction\n\n{instr}")
        dial = _dial_block(config)
        parts.append(dial or "## Experience settings\n\n(defaults)")
        if config.get("target_length"):
            parts.append(f"## Target length\n\nabout {config['target_length']} characters")
        lang = language or "auto"
        parts.append(f"## Expected language\n\n{lang}")
        if avoid:
            parts.append(
                "## Avoid (genuinely different from these)\n\n"
                + "\n".join(f"- {a}" for a in avoid[:3]))
        user = "\n\n".join(parts)
        result = self.client.generate_text(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": user}],
            role="suggest_instruction",
            role_cfg=self.config.role("writer"))
        text = (result.text or "").strip()
        if not text:
            raise GenerationFailed("We couldn't draft an instruction. Please retry.")
        return text
    def suggest_topics(self, *, domain=None, object_name=None, tension=None,
                       avoid=None, config=None, count=8, hint=None,
                       seed=None) -> dict:
        """Propose a batch of discussable topics (default 8).

        Two modes: with a `seed` (the user's own sentence/phenomenon), all
        topics press on the seed's underlying structure as different facets
        and no sampled axes are injected. Without a seed, the batch roams
        the domain: the prompt demands a different Concrete Anchor per
        topic and the engine samples `count` distinct tension axes
        (taxonomy §6) requiring one topic per axis.
        """
        import dataclasses
        import random

        # Reasoning models + long prompt + json_object intermittently return
        # empty content on this gateway (V1 report §4 family of bugs); a
        # short creative task needs no reasoning anyway — use a lite cfg.
        lite = dataclasses.replace(self.config.role("architect"),
                                   reasoning_effort="",
                                   max_output_tokens=3000,
                                   temperature=0.75)
        count = max(3, min(12, int(count or 8)))
        seed = (seed or "").strip() or None
        tax = _load_topic_taxonomy()
        axes = [] if seed else random.sample(
            [t["name"] for t in tax["tensions"]], count)
        sys_prompt = _load_prompt(self.config.prompts_dir, "topic_suggest")
        parts = [
            f"## Batch size\n\n{count}",
            f"## Domain\n\n{domain or '(不限 — roam across all domains)'}",
            f"## Object (Concrete Anchor)\n\n"
            f"{object_name or '(不限 — 每条话题自选一个不同的具体锚点)'}",
            f"## Tension\n\n{tension or '(不限 — 使用下方指定轴)'}"]
        if axes:
            parts.append("## Required tension axes (one per topic, in order)"
                         "\n\n" + "\n".join(f"- {a}" for a in axes))
        if seed:
            parts.append(f"## User seed (their own thinking)\n\n{seed[:200]}")
        if hint:
            parts.append(f"## User steer (optional direction)\n\n{hint[:100]}")
        if avoid:
            parts.append("## Avoid (genuinely different from these)\n\n"
                         + "\n".join(f"- {a}" for a in avoid[:24]))
        parts.append("## Language\n\nChinese (zh)")
        try:
            stage = structured_call(
                self.client, role="topic_suggest",
                role_cfg=lite,
                system_prompt=sys_prompt, user_message="\n\n".join(parts),
                validator=validate_topics)
        except StructuredOutputError as exc:
            raise GenerationFailed(
                "We couldn't suggest topics. Please retry.") from exc
        return stage.data

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


def _load_topic_taxonomy():
    """Static, versioned topic taxonomy (workbench/taxonomy.json).

    Loaded here rather than via the service layer: the engine sits below
    the product service and must not import upward.
    """
    from functools import lru_cache
    from pathlib import Path

    @lru_cache(maxsize=1)
    def _read():
        p = Path(__file__).resolve().parent.parent / "taxonomy.json"
        return json.loads(p.read_text(encoding="utf-8"))
    return _read()


_DIAL_GUIDANCE = {
    ("immersion", "high"): "immersion high: stay inside scenes — render moments through action, dialogue, sensory detail; minimize summary.",
    ("immersion", "medium"): "immersion medium: alternate between scene presentation and compact summary.",
    ("immersion", "low"): "immersion low: summary and exposition are acceptable; do not dramatize every beat into a scene.",
    ("explicitness", "high"): "explicitness high: the writer's point may be stated directly at key moments.",
    ("explicitness", "medium"): "explicitness medium: state the point plainly only where the reader would otherwise get lost.",
    ("explicitness", "low"): "explicitness low: do not state the theme; let meaning emerge from images, detail and structure.",
    ("intensity", "high"): "intensity high: emotional stakes are strong and present; language may run hot.",
    ("intensity", "medium"): "intensity medium: moderate emotional charge, with variation.",
    ("intensity", "low"): "intensity low: restraint — understated language, emotion carried by concrete details, not stated.",
}


def _meaning_text(meaning: dict) -> str:
    block = meaning_to_wir_block(meaning)
    return "\n".join(str(v) for v in block.values() if v)


def resolve_language_for(config: dict, material: str, instruction: str,
                        meaning: dict | None, default: str) -> str:
    """Topic-led pieces gate on the discovery language, not the seed topic."""
    probe_instruction = instruction or ""
    if meaning:
        probe_instruction += "\n" + _meaning_text(meaning)
    return resolve_expected_language(
        {"expected_language": config.get("expected_language"),
         "instruction": probe_instruction, "material": material}, default)


_GATE_REASON_ZH = [
    ("language mismatch", "语言与预期不符"),
    ("output too short", "输出过短"),
    ("length", "篇幅与目标字数差距过大"),
    ("refusal", "模型拒绝了这次写作"),
    ("format leakage", "正文混入了内部格式"),
    ("unsupported numerals", "出现了素材中没有的数字"),
    ("unsupported latin names", "出现了素材中没有的英文专名"),
    ("unsupported long quotation", "出现了素材中没有的长引用"),
]


def _gate_message(reasons: list[str]) -> str:
    out = []
    for r in reasons or []:
        for key, zh in _GATE_REASON_ZH:
            if key in r and zh not in out:
                out.append(zh)
                break
    return "、".join(out) or "未通过检查"


def _outline_summary(wir: dict) -> str:
    """Product-safe one-line outline preview (no raw WIR JSON to the UI)."""
    beats = (wir or {}).get("beats") or []
    gains = [(b.get("meaning_gain") or b.get("function", {}).get("primary")
              or "").strip() for b in beats]
    gains = [g for g in gains if g]
    if not gains:
        return "结构已确定。"
    shown = gains[:4]
    tail = f" 等 {len(gains)} 步" if len(gains) > 4 else ""
    return "结构:" + " → ".join(shown) + tail


def _dial_block(config: dict) -> str:
    lines = []
    for key in ("immersion", "explicitness", "intensity"):
        hint = _DIAL_GUIDANCE.get((key, (config or {}).get(key)))
        if hint:
            lines.append(f"- {hint}")
    if not lines:
        return ""
    return ("## Experience settings (set deliberately by the writer; honor all three)\n\n"
            + "\n".join(lines) + "\n\n")


def _compose_topic_instruction(instruction: str, meaning: dict) -> str:
    """Feed the selected meaning explicitly into the WIR stage (product/13 §Output to WIR)."""
    from ..meaning_schema import PROGRESSION_CONTRACT
    block = meaning_to_wir_block(meaning)
    lines = ["## Meaning to develop (do not replace this thesis)", ""]
    lines.append(f"Refined thesis: {block['refined_thesis'] or block['deep_meaning']}")
    lines.append(f"Selected angle: {block['selected_angle']}")
    lines.append(f"Core question: {block['core_question']}")
    lines.append(f"Deep meaning: {block['deep_meaning']}")
    lines.append(f"Reader should end understanding: {block['reader_end_state']}")
    if block.get("strongest_counterexample"):
        lines.append(f"Strongest counterexample to face: {block['strongest_counterexample']}")
    if block.get("boundary"):
        lines.append(f"Boundary of the thesis: {block['boundary']}")
    if block["key_tensions"]:
        lines.append("Key tensions: " + "; ".join(block["key_tensions"]))
    lines += ["", PROGRESSION_CONTRACT, "",
              "This piece is topic-led (not source-grounded). Do not invent "
              "citations or claim unsupported authority.", ""]
    if instruction:
        lines.append("## Writer's own note")
        lines.append(instruction)
    return "\n".join(lines)
