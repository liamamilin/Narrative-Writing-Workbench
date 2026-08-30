"""Ablation variant runners (docs/14 §3, docs/16).

V1.1:
  A1      conventional outline -> writer_outline
  A2      Reader-State WIR -> writer            (no critic, no patcher)
  A2_GI   Reader-State WIR -> writer_gi         (experimental, docs/15)
  A3      full V1 pipeline (== B3)
  A3_GI   full pipeline with writer swapped to writer_gi (optional)

V1.2 clean causal ablation (docs/16): one shared WIR per case, one shared
draft per Critic experiment:

  A1      outline -> writer_outline            (H2 side)
  A2      WIR -> W0 writer  == D0 for H3 == W0 for H4 (one run, shared)
  A3      D1 = Critic/Patch applied to the SAME A2 draft
  WGI     WIR -> writer_gi  == GI_D0 for H5 (same shared WIR as A2)
  GI_A3   GI_D1 = Critic/Patch applied to the SAME WGI draft

Generation settings are pinned to the V1 role configs (outline architect
reuses the architect role config; GI writers reuse the writer role config),
so architecture is the primary changing variable.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from .architect import ArchitectAgent
from .evaluation import rule_diagnostics
from .config import Config
from .critic import CriticAgent
from .gates import detect_language, resolve_expected_language
from .language import write_with_language_repair
from .llm_client import LLMClient, build_client
from .models import Usage
from .outline import OutlineArchitectAgent
from .patcher import PatcherAgent
from .pipeline import Pipeline
from .schemas import SchemaSet
from .writer import WriterAgent

logger = logging.getLogger(__name__)

VARIANTS = ("A1", "A2", "A3", "A2_GI", "A3_GI")

WRITER_OF = {
    "A1": "writer_outline",
    "A2": "writer",
    "A2_GI": "writer_gi",
}


class VariantRunner:
    def __init__(
        self,
        config: Config | None = None,
        client: LLMClient | None = None,
        schemas: SchemaSet | None = None,
    ):
        self.config = config or Config.default()
        self.client = client or build_client(self.config)
        self.schemas = schemas or SchemaSet(self.config.schemas_dir)
        self.architect = ArchitectAgent(self.client, self.config, self.schemas)
        self.outline_architect = OutlineArchitectAgent(
            self.client, self.config, self.schemas
        )
        self.writers = {
            name: WriterAgent(self.client, self.config, prompt_file=name)
            for name in ("writer", "writer_gi", "writer_outline")
        }
        self.pipeline = Pipeline(self.config, client=self.client,
                                 schemas=self.schemas)

    # ------------------------------------------------------------------

    def run(self, case: dict, variant: str) -> dict:
        """Run one case under one ablation variant; return an output row."""
        if variant not in VARIANTS:
            raise ValueError(f"unknown ablation variant '{variant}' (supported: {VARIANTS})")
        try:
            if variant == "A1":
                return self._run_a1(case)
            if variant in ("A2", "A2_GI"):
                return self._run_a2(case, variant)
            if variant == "A3":
                return self._run_a3(case, gi=False)
            return self._run_a3(case, gi=True)  # A3_GI
        except Exception as exc:  # noqa: BLE001 — row-level isolation
            logger.exception("variant %s failed for case %s", variant, case.get("id"))
            return {"case_id": case["id"], "baseline": variant,
                    "status": "failed", "text": None, "error": str(exc)}

    # ------------------------------------------------------------------

    def _run_a1(self, case: dict) -> dict:
        task_type = case.get("task_type", "narrative_commentary")
        st_out = self.outline_architect.run(
            case["material"], case["instruction"], task_type
        )
        st_txt = self.writers["writer_outline"].run(
            case["material"], case["instruction"], st_out.data,
            structure_label="Outline (validated; immutable input)",
        )
        return {
            "case_id": case["id"], "baseline": "A1", "status": "success",
            "text": st_txt.data,
            "structure": st_out.data,
            "diagnostics": rule_diagnostics(st_txt.data or ""),
            "usage": st_out.usage.add(st_txt.usage).to_dict(),
            "repair_used": bool(st_out.repair_used or st_txt.repair_used),
        }

    def _run_a2(self, case: dict, variant: str) -> dict:
        task_type = case.get("task_type", "narrative_commentary")
        constraints = {"target_length": case.get("target_length")}
        st_wir = self.architect.run(
            case["material"], case["instruction"], task_type, constraints
        )
        st_txt = self.writers[WRITER_OF[variant]].run(
            case["material"], case["instruction"], st_wir.data
        )
        return {
            "case_id": case["id"], "baseline": variant, "status": "success",
            "text": st_txt.data,
            "structure": st_wir.data,
            "diagnostics": rule_diagnostics(st_txt.data or ""),
            "usage": st_wir.usage.add(st_txt.usage).to_dict(),
            "repair_used": bool(st_wir.repair_used or st_txt.repair_used),
        }

    def _run_a3(self, case: dict, gi: bool) -> dict:
        variant = "A3_GI" if gi else "A3"
        original = self.pipeline.writer
        if gi:
            self.pipeline.writer = self.writers["writer_gi"]
        try:
            res = self.pipeline.run(
                material=case["material"],
                instruction=case["instruction"],
                task_type=case.get("task_type", "narrative_commentary"),
                constraints={"target_length": case.get("target_length")},
            )
        finally:
            self.pipeline.writer = original
        if not res.ok:
            return {"case_id": case["id"], "baseline": variant, "status": "failed",
                    "text": None, "run_id": res.run_id, "errors": res.errors}
        critique = res.critique or {}
        return {
            "case_id": case["id"], "baseline": variant, "status": "success",
            "text": res.final_text,
            "structure": res.wir,
            "diagnostics": rule_diagnostics(res.final_text or ""),
            "run_id": res.run_id,
            "patched": res.patched,
            "decision": critique.get("decision"),
            "writing_quality": (
                sum((critique.get("quality") or {}).values()) if critique else None
            ),
            "usage": res.usage.to_dict(),
        }


# ======================================================================
# V1.2 clean causal ablation (docs/16)
# ======================================================================

V12_ROWS = ("A1", "A2", "A3", "WGI", "GI_A3")
V12_PAIRS = (
    ("A2", "A1"),       # P1 / H2-clean: WIR vs conventional outline
    ("A3", "A2"),       # P2 / H3-clean: Critic/Patch on the SAME draft
    ("WGI", "W0"),      # P3 / H4-confirm: writer policy on the SAME WIR
    ("GI_A3", "WGI"),   # P4 / H5: Critic/Patch on the SAME GI draft
)
V12_ALIAS = {"W0": "A2"}  # one shared production-Writer run serves P1/P2/P3


class V12Runner:
    """Per-case runner for the V1.2 clean ablation.

    One WIR and one outline are generated per case and shared by all rows;
    A3/GI_A3 branch from the EXACT SAME draft as their control side, so the
    only manipulated variable is Critic/Patch (docs/16 §4-§5).
    """

    def __init__(
        self,
        config: Config | None = None,
        client: LLMClient | None = None,
        schemas: SchemaSet | None = None,
    ):
        self.config = config or Config.default()
        self.client = client or build_client(self.config)
        self.schemas = schemas or SchemaSet(self.config.schemas_dir)
        self.architect = ArchitectAgent(self.client, self.config, self.schemas)
        self.outline_architect = OutlineArchitectAgent(
            self.client, self.config, self.schemas
        )
        self.writers = {
            name: WriterAgent(self.client, self.config, prompt_file=name)
            for name in ("writer", "writer_gi", "writer_outline")
        }
        self.critic = CriticAgent(self.client, self.config, self.schemas)
        self.patcher = PatcherAgent(self.client, self.config)

    # ------------------------------------------------------------------

    def run_case(self, case: dict) -> list[dict]:
        """Run one case through the shared-draft graph; returns 5 rows."""
        material = case["material"]
        instruction = case["instruction"]
        task_type = case.get("task_type", "narrative_commentary")
        tl = case.get("target_length")
        exp = resolve_expected_language(case, self.config.expected_language)

        try:
            st_wir = self.architect.run(material, instruction, task_type,
                                        {"target_length": tl})
        except Exception as exc:  # noqa: BLE001 — whole case lost
            logger.exception("v12 architect failed for case %s", case.get("id"))
            return [self._failed_row(case, v, f"architect: {exc}")
                    for v in V12_ROWS]
        try:
            st_out = self.outline_architect.run(material, instruction, task_type)
        except Exception as exc:  # noqa: BLE001 — only A1 is lost
            logger.exception("v12 outline architect failed for case %s", case.get("id"))
            st_out = None

        rows: list[dict] = []
        if st_out is not None:
            rows.append(self._row_writer(
                case, "A1", st_out.data, "writer_outline",
                "Outline (validated; immutable input)", exp, tl,
                structure_usage=st_out.usage))
        else:
            rows.append(self._failed_row(case, "A1", "outline architect failed"))

        a2 = self._row_writer(case, "A2", st_wir.data, "writer",
                              "WIR (validated; immutable input)", exp, tl,
                              structure_usage=st_wir.usage)
        rows.append(a2)
        rows.append(self._row_patched(case, "A3", a2, st_wir.data))

        wgi = self._row_writer(case, "WGI", st_wir.data, "writer_gi",
                               "WIR (validated; immutable input)", exp, tl)
        rows.append(wgi)
        rows.append(self._row_patched(case, "GI_A3", wgi, st_wir.data))
        return rows

    # ------------------------------------------------------------------

    def _row_writer(self, case, variant, structure, prompt_file,
                    structure_label, exp, tl,
                    structure_usage: Usage | None = None) -> dict:
        """One Writer-policy run with the language repair policy (docs/17)."""
        try:
            res = write_with_language_repair(
                self.writers[prompt_file],
                material=case["material"], instruction=case["instruction"],
                structure=structure, expected_language=exp,
                structure_label=structure_label, target_length=tl,
            )
        except Exception as exc:  # noqa: BLE001 — row-level isolation
            return self._failed_row(case, variant, f"writer: {exc}")
        usage = (structure_usage or Usage()).add(res.usage)
        row = {
            "case_id": case["id"], "baseline": variant,
            "status": "success", "text": res.text,
            "structure": structure,
            "draft_id": f"{case['id']}:{variant}",
            "diagnostics": rule_diagnostics(res.text or ""),
            "usage": usage.to_dict(),
            "repair_used": res.repair_used,
            **res.to_row_fields(),
        }
        if res.functional_failure:
            # Language repair failed: not a final Writer sample; never sent
            # to the Critic. The failed generation is preserved (docs/17 §3).
            row["status"] = "failed"
            row["error"] = "language_functional_failure"
            row["original_text"] = res.original_text
            row["gates"] = self._gates(res.text, case)
        return row

    def _row_patched(self, case, variant, source: dict, structure) -> dict:
        """Critic/Patch applied to the SAME source draft (docs/16 §4)."""
        lineage = {
            "source_draft_id": source.get("draft_id"),
            "critic_decision": None,
            "patched": False,
            "patch_targets": [],
            "final_draft_id": f"{case['id']}:{variant}",
        }
        if source.get("status") != "success":
            return self._failed_row(
                case, variant,
                f"source draft unavailable ({source.get('error') or source.get('status')})",
                lineage=lineage)
        critic_usage = Usage()
        patch_usage = Usage()
        patch_calls = 0
        try:
            st_c = self.critic.run(case["material"], case["instruction"],
                                   structure, source["text"])
            critic_usage = st_c.usage
            critique = st_c.data
            decision = critique.get("decision")
            lineage["critic_decision"] = decision
            lineage["patch_targets"] = list(critique.get("patch_targets") or [])
            if decision == "PATCH_REQUIRED":
                st_p = self.patcher.run(case["material"], case["instruction"],
                                        structure, source["text"], critique)
                patch_usage = st_p.usage
                patch_calls = 1
                final_text = st_p.data
                lineage["patched"] = True
            else:
                # PASS: D1 == D0 byte-identical. No regeneration, no forcing.
                final_text = source["text"]
        except Exception as exc:  # noqa: BLE001
            return self._failed_row(case, variant, f"critic/patcher: {exc}",
                                    lineage=lineage)
        usage = critic_usage.add(patch_usage)
        return {
            "case_id": case["id"], "baseline": variant,
            "status": "success", "text": final_text,
            "structure": structure,
            "draft_id": lineage["final_draft_id"],
            "decision": lineage["critic_decision"],
            "patched": lineage["patched"],
            "lineage": lineage,
            "diagnostics": rule_diagnostics(final_text or ""),
            "usage": usage.to_dict(),
            "cost": {
                "critic_calls": 1,
                "patch_calls": patch_calls,
                "critic_input_tokens": critic_usage.input_tokens,
                "critic_output_tokens": critic_usage.output_tokens,
                "critic_cost": critic_usage.estimated_cost,
                "critic_latency_seconds": critic_usage.latency_seconds,
                "patch_input_tokens": patch_usage.input_tokens,
                "patch_output_tokens": patch_usage.output_tokens,
                "patch_cost": patch_usage.estimated_cost,
                "patch_latency_seconds": patch_usage.latency_seconds,
                "latency_added_seconds": round(
                    critic_usage.latency_seconds + patch_usage.latency_seconds, 3),
            },
            "language_attempts": source.get("language_attempts"),
            "language_repaired": source.get("language_repaired"),
            "language_functional_failure": False,
            "original_language": source.get("original_language"),
            "final_language": detect_language(final_text or ""),
        }

    def _failed_row(self, case, variant, error, lineage=None) -> dict:
        row = {"case_id": case["id"], "baseline": variant, "status": "failed",
               "text": None, "error": error}
        if lineage:
            row["lineage"] = lineage
        return row

    def _gates(self, text, case):
        from .gates import hard_gates
        return hard_gates(text or "", case)
