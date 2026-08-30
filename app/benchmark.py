"""Smoke benchmark runner.

Baselines (docs/07) and ablation variants (docs/14):
  B0    Direct          — minimal quality instruction, single generation
  B1    Strong Prompt   — detailed writing prompt, single generation
  A1    Outline         — conventional outline -> writer (no reader-state)
  A2    WIR             — Reader-State WIR -> writer (no critic/patcher)
  A2_GI WIR + GI        — grounded-immersion writer (docs/15, experimental)
  A3    Full pipeline   — WIR -> writer -> critic -> optional patch (== B3)
  B3    alias of A3 (V1 label, kept for backward compatibility)

All outputs are persisted under:

  benchmarks/results/<experiment_id>/
    config.json outputs.jsonl gates.jsonl artifacts/ judgments.jsonl
    summary.json pairwise_packets.jsonl pairwise_key.jsonl diagnostics.jsonl

Prompts are NOT tuned on benchmark outputs during the same run (docs/07 §9).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

from .config import Config
from .evaluation import DIMENSIONS, aggregate_judgments, build_pairwise_packets, llm_judge_pair, rule_diagnostics
from .gates import hard_gates
from .llm_client import LLMClient, build_client
from .pipeline import Pipeline
from .utils import now_iso, sha256_text
from .variants import V12_ALIAS, V12_PAIRS, V12_ROWS, V12Runner, VariantRunner

logger = logging.getLogger(__name__)

BASELINE_FILES = {
    "B0": "B0_direct.md",
    "B1": "B1_strong.md",
}
ALL_BASELINES = ("B0", "B1", "A1", "A2", "A2_GI", "A3", "A3_GI", "B3", "WGI", "GI_A3")
ABLATION_PAIRS = (
    ("A2", "A1"),      # H2: Reader-State WIR contribution
    ("A3", "A2"),      # H3: Critic/Patch contribution
    ("A3", "B1"),      # full architecture vs strong single-pass prompting
    ("A2_GI", "A2"),   # H4: grounded immersion effect
)


def load_cases(path: str | Path) -> list[dict]:
    cases: list[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL line: {exc}") from exc
            for required in ("id", "material", "instruction"):
                if required not in case:
                    raise ValueError(f"{path}:{line_no}: case missing '{required}'")
            cases.append(case)
    return cases


def _case_by_id(cases: list[dict], case_id: str) -> dict:
    for c in cases:
        if c["id"] == case_id:
            return c
    raise KeyError(case_id)


class BenchmarkRunner:
    def __init__(
        self,
        config: Config | None = None,
        client: LLMClient | None = None,
        baselines_dir: str | Path | None = None,
    ):
        self.config = config or Config.default()
        self.client = client or build_client(self.config)
        self.pipeline = Pipeline(self.config, client=self.client)
        self.variant_runner = VariantRunner(self.config, client=self.client)
        self.v12_runner = V12Runner(self.config, client=self.client)
        self.baselines_dir = Path(
            baselines_dir
            or Path(__file__).resolve().parent.parent / "benchmarks" / "baselines"
        )

    def baseline_prompt(self, baseline: str) -> str:
        return (self.baselines_dir / BASELINE_FILES[baseline]).read_text(encoding="utf-8").strip()

    # ------------------------------------------------------------------

    def run(
        self,
        cases_path: str | Path,
        baselines: tuple[str, ...] = ALL_BASELINES,
        experiment_id: str | None = None,
        pairs: tuple[tuple[str, str], ...] | None = None,
    ) -> dict:
        for b in baselines:
            if b not in ALL_BASELINES:
                raise ValueError(f"unknown baseline '{b}' (supported: {ALL_BASELINES})")
        cases = load_cases(cases_path)
        experiment_id = experiment_id or time.strftime("exp_%Y%m%d_%H%M%S")
        out_dir = Path(self.config.benchmark_results_dir) / experiment_id
        out_dir.mkdir(parents=True, exist_ok=True)

        v12 = bool(baselines) and all(b in V12_ROWS for b in baselines)

        outputs: list[dict] = []
        if v12:
            # V1.2 clean ablation: one shared-draft graph per case (docs/16).
            for case in cases:
                logger.info("benchmark %s: case %s / v12", experiment_id, case["id"])
                for row in self.v12_runner.run_case(case):
                    self._finish_row(row, case, out_dir, outputs)
            # Alias rows: the single A2 run is also W0 for the H4 pair.
            targets = set(V12_ALIAS.values())
            for row in [r for r in outputs if r["baseline"] in targets]:
                for alias, target in V12_ALIAS.items():
                    if target != row["baseline"]:
                        continue
                    aliased = dict(row)
                    aliased["baseline"] = alias
                    aliased["alias_of"] = target
                    aliased["draft_id"] = f"{row['case_id']}:{alias}"
                    self._finish_row(aliased, _case_by_id(cases, row["case_id"]),
                                     out_dir, outputs, compute_gates=False)
        else:
            for case in cases:
                for baseline in baselines:
                    logger.info("benchmark %s: case %s / %s", experiment_id, case["id"], baseline)
                    if baseline == "B3":
                        row = self._run_b3(case)
                    elif baseline in ("A1", "A2", "A2_GI", "A3", "A3_GI"):
                        row = self.variant_runner.run(case, baseline)
                    else:
                        row = self._run_direct(case, baseline)
                    self._finish_row(row, case, out_dir, outputs)

        return self._finalize(out_dir, experiment_id, cases, baselines, outputs,
                              pairs, auto_tie=v12)

    @staticmethod
    def _finish_row(row: dict, case: dict, out_dir: Path,
                    outputs: list[dict], compute_gates: bool = True) -> None:
        if compute_gates and not row.get("gates"):
            if row.get("status") == "success":
                row["gates"] = hard_gates(row.get("text") or "", case)
            else:
                g = hard_gates("", case)
                g["functional_failure"] = True
                g["failure_reasons"] = g["failure_reasons"] + ["generation failed"]
                row["gates"] = g
        outputs.append(row)
        BenchmarkRunner._append_jsonl(out_dir / "outputs.jsonl", row)
        BenchmarkRunner._persist_artifact(out_dir, row)

    # ------------------------------------------------------------------

    @staticmethod
    def _persist_artifact(out_dir: Path, row: dict) -> None:
        """Persist intermediate structure (outline/WIR) + text for every variant
        that has one (docs/14 §7)."""
        art_dir = out_dir / "artifacts"
        art_dir.mkdir(exist_ok=True)
        payload = {
            "case_id": row["case_id"],
            "variant": row["baseline"],
            "status": row.get("status"),
            "structure": row.get("structure"),
            "text": row.get("text"),
            "usage": row.get("usage"),
            "gates": row.get("gates"),
        }
        if row.get("run_id"):
            payload["run_id"] = row["run_id"]
        for key in ("draft_id", "lineage", "cost", "alias_of", "error",
                    "original_text", "language_attempts", "language_repaired",
                    "language_functional_failure", "original_language",
                    "final_language"):
            if row.get(key) is not None:
                payload[key] = row[key]
        path = art_dir / f"{row['case_id']}_{row['baseline']}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # ------------------------------------------------------------------

    def _run_direct(self, case: dict, baseline: str) -> dict:
        prompt = self.baseline_prompt(baseline)
        user = (
            f"## 材料\n\n{case['material']}\n\n"
            f"## 任务要求\n\n{case['instruction']}\n\n"
            f"目标长度：约 {case.get('target_length', '不限')} 字。"
        )
        role_cfg = self.config.role("writer")
        try:
            result = self.client.generate_text(
                [{"role": "system", "content": prompt},
                 {"role": "user", "content": user}],
                role="baseline",
                role_cfg=role_cfg,
            )
            return {
                "case_id": case["id"],
                "baseline": baseline,
                "status": "success",
                "text": result.text,
                "usage": {
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "latency_seconds": result.latency_seconds,
                },
                "diagnostics": rule_diagnostics(result.text),
            }
        except Exception as exc:
            return {"case_id": case["id"], "baseline": baseline,
                    "status": "failed", "text": None, "error": str(exc)}

    def _run_b3(self, case: dict) -> dict:
        constraints = {"target_length": case.get("target_length")}
        try:
            res = self.pipeline.run(
                material=case["material"],
                instruction=case["instruction"],
                task_type=case.get("task_type", "narrative_commentary"),
                constraints=constraints,
            )
            if not res.ok:
                return {"case_id": case["id"], "baseline": "B3", "status": "failed",
                        "text": None, "run_id": res.run_id, "errors": res.errors}
            critique = res.critique or {}
            return {
                "case_id": case["id"],
                "baseline": "B3",
                "status": "success",
                "text": res.final_text,
                "run_id": res.run_id,
                "patched": res.patched,
                "decision": critique.get("decision"),
                "writing_quality": (
                    sum((critique.get("quality") or {}).values()) if critique else None
                ),
                "usage": res.usage.to_dict(),
                "diagnostics": rule_diagnostics(res.final_text or ""),
            }
        except Exception as exc:
            return {"case_id": case["id"], "baseline": "B3", "status": "failed",
                    "text": None, "error": str(exc)}

    # ------------------------------------------------------------------

    def _finalize(
        self,
        out_dir: Path,
        experiment_id: str,
        cases: list[dict],
        baselines: tuple[str, ...],
        outputs: list[dict],
        pairs: tuple[tuple[str, str], ...] | None = None,
        auto_tie: bool = False,
    ) -> dict:
        # Reproducibility record (docs/09 §7).
        cfg_info = {
            "experiment_id": experiment_id,
            "timestamp": now_iso(),
            "provider": self.config.provider,
            "models": {name: rc.model for name, rc in self.config.roles.items()},
            "parameters": {
                name: {
                    "temperature": rc.temperature,
                    "max_output_tokens": rc.max_output_tokens,
                    "structured_mode": rc.structured_mode,
                }
                for name, rc in self.config.roles.items()
            },
            "baselines": list(baselines),
            "case_ids": [c["id"] for c in cases],
            "baseline_prompt_hashes": {
                b: sha256_text(self.baseline_prompt(b)) for b in baselines if b in BASELINE_FILES
            },
            "thresholds": asdict(self.config.thresholds),
        }
        (out_dir / "config.json").write_text(
            json.dumps(cfg_info, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Hard-gate records, stored separately from literary quality (docs/14 §5).
        with open(out_dir / "gates.jsonl", "w", encoding="utf-8") as fh:
            for r in outputs:
                if r.get("gates"):
                    fh.write(json.dumps(
                        {"case_id": r["case_id"], "variant": r["baseline"],
                         "status": r.get("status"), **r["gates"]},
                        ensure_ascii=False) + "\n")

        # Anonymous pairwise packaging. Default: system vs direct baselines
        # (V1 behavior). Ablation runs pass explicit pairs (docs/14 §6).
        if pairs is None:
            pairs = tuple(
                (sys_b, base_b)
                for sys_b in ("B3", "A3") if any(
                    r["baseline"] == sys_b for r in outputs)
                for base_b in ("B0", "B1")
            )
            if not pairs:
                pairs = (("B3", "B0"), ("B3", "B1"))
        packets: list[dict] = []
        key: list[dict] = []
        for system_baseline, target_baseline in pairs:
            p, k = build_pairwise_packets(
                outputs, target_baselines=(target_baseline,),
                system_baseline=system_baseline)
            packets.extend(p)
            key.extend(k)
        dropped_failed_sides = 0
        if auto_tie:
            # A language-functional failure means the sample is not final
            # (docs/17 §3): pairs with a failed side are not packaged.
            status = {(r["case_id"], r["baseline"]): r.get("status")
                      for r in outputs}
            keep = [i for i, (p, k) in enumerate(zip(packets, key))
                    if status.get((p["case_id"], k["a"])) == "success"
                    and status.get((p["case_id"], k["b"])) == "success"]
            dropped_failed_sides = len(packets) - len(keep)
            packets = [packets[i] for i in keep]
            key = [key[i] for i in keep]
        # V1.2 deterministic policy (docs/16 §6): byte-identical pairs (Critic
        # PASS => D1 == D0) are auto-recorded as all-dimension ties and are
        # excluded from the manual review workload. Raw judgments are never
        # mutated; auto ties carry reviewer="auto_tie".
        judgments_path = out_dir / "judgments.jsonl"
        auto_ties: list[dict] = []
        for p in packets:
            identical = bool(p["text_a"]) and p["text_a"] == p["text_b"]
            if auto_tie:
                p["identical"] = identical
            if identical and auto_tie:
                auto_ties.append({
                    "case_id": p["case_id"], "pair": p["pair"],
                    "winner": "Tie",
                    "dimensions": {d: "Tie" for d in DIMENSIONS},
                    "rationale": "byte-identical pair (Critic PASS): "
                                 "deterministic auto-tie (docs/16 §6)",
                    "reviewer": "auto_tie",
                })
        for p in packets:
            self._append_jsonl(out_dir / "pairwise_packets.jsonl", p)
        for k in key:
            self._append_jsonl(out_dir / "pairwise_key.jsonl", k)
        for j in auto_ties:
            self._append_jsonl(judgments_path, j)

        # Optional LLM judge (off by default; benchmark outputs are never used
        # to tune prompts in the same run).
        judgments: list[dict] = []
        if self.config.judge_enabled and packets:
            for packet in packets:
                if packet.get("identical"):
                    continue
                try:
                    j = llm_judge_pair(self.client, self.config, packet)
                    judgments.append(j)
                    self._append_jsonl(judgments_path, j)
                except Exception as exc:
                    logger.warning("judge failed for %s/%s: %s",
                                   packet["case_id"], packet["pair"], exc)
        else:
            judgments_path.touch(exist_ok=True)

        diagnostics_rows = [
            {"case_id": r["case_id"], "baseline": r["baseline"], "diagnostics": r["diagnostics"]}
            for r in outputs if r.get("diagnostics")
        ]
        with open(out_dir / "diagnostics.jsonl", "w", encoding="utf-8") as fh:
            for row in diagnostics_rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

        summary = self._summary(outputs, judgments, key)
        summary["mode"] = "v12_clean_ablation" if auto_tie else "v1"
        if auto_tie:
            summary["v12"] = self._v12_stats(outputs, packets, auto_ties)
            summary["v12"]["pairs"]["dropped_failed_side"] = dropped_failed_sides
        (out_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("benchmark %s: results in %s", experiment_id, out_dir)
        return {"experiment_id": experiment_id, "dir": str(out_dir), "summary": summary}

    @staticmethod
    def _summary(outputs: list[dict], judgments: list[dict], key: list[dict]) -> dict:
        per_baseline: dict[str, dict] = {}
        for r in outputs:
            b = r["baseline"]
            entry = per_baseline.setdefault(
                b, {"n": 0, "success": 0, "failed": 0, "total_chars": 0,
                    "patched": 0, "hard_fail": 0, "wq_scores": []})
            entry["n"] += 1
            if (r.get("gates") or {}).get("functional_failure"):
                entry["hard_fail"] += 1
            if r.get("status") == "success":
                entry["success"] += 1
                entry["total_chars"] += len(r.get("text") or "")
                if r.get("patched"):
                    entry["patched"] += 1
                if r.get("writing_quality") is not None:
                    entry["wq_scores"].append(r["writing_quality"])
            else:
                entry["failed"] += 1
        for entry in per_baseline.values():
            scores = entry.pop("wq_scores")
            entry["mean_wq"] = round(sum(scores) / len(scores), 2) if scores else None
            entry["mean_chars"] = round(entry.pop("total_chars") / max(1, entry["success"]), 1)
        return {
            "cases": len({r["case_id"] for r in outputs}),
            "per_baseline": per_baseline,
            "pairwise": aggregate_judgments(judgments, key) if judgments else {},
        }

    @staticmethod
    def _v12_stats(outputs: list[dict], packets: list[dict],
                   auto_ties: list[dict]) -> dict:
        """Language-repair, Critic PASS/PATCH and cost metrics (docs/16 §7)."""
        per: dict[str, dict] = {}
        for r in outputs:
            if r.get("alias_of"):
                continue
            b = r["baseline"]
            e = per.setdefault(b, {"runs": 0, "success": 0, "failed": 0,
                                   "language_attempts": 0, "language_repairs": 0,
                                   "language_functional_failures": 0,
                                   "total_chars": 0})
            e["runs"] += 1
            e["language_attempts"] += int(r.get("language_attempts") or 0)
            if r.get("language_repaired"):
                e["language_repairs"] += 1
            if r.get("language_functional_failure"):
                e["language_functional_failures"] += 1
            if r.get("status") == "success":
                e["success"] += 1
                e["total_chars"] = e.get("total_chars", 0) + len(r.get("text") or "")
            else:
                e["failed"] += 1
        for b, e in per.items():
            e["mean_chars"] = round(e.pop("total_chars") / max(1, e["success"]), 1)
            critic_rows = [r for r in outputs if r["baseline"] == b and r.get("cost")]
            if critic_rows:
                e["critic_calls"] = len(critic_rows)
                e["critic_pass"] = sum(1 for r in critic_rows
                                       if (r.get("lineage") or {}).get("critic_decision") == "PASS")
                e["critic_patch_required"] = sum(1 for r in critic_rows
                                                 if r["cost"]["patch_calls"])
                e["patch_calls"] = sum(r["cost"]["patch_calls"] for r in critic_rows)
                e["critic_output_tokens"] = sum(r["cost"]["critic_output_tokens"] for r in critic_rows)
                e["patch_output_tokens"] = sum(r["cost"]["patch_output_tokens"] for r in critic_rows)
                e["critic_cost"] = round(sum(r["cost"]["critic_cost"] for r in critic_rows), 4)
                e["patch_cost"] = round(sum(r["cost"]["patch_cost"] for r in critic_rows), 4)
                e["latency_added_seconds"] = round(
                    sum(r["cost"]["latency_added_seconds"] for r in critic_rows), 2)
        identical = sum(1 for p in packets if p.get("identical"))
        return {
            "per_variant": per,
            "pairs": {
                "total": len(packets),
                "identical_auto_tie": identical,
                "manual_review": len(packets) - identical,
            },
            "auto_tie_judgments": len(auto_ties),
        }

    @staticmethod
    def _append_jsonl(path: Path, obj: dict) -> None:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
