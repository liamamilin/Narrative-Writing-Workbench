"""Dry-run the full smoke benchmark with a scripted MockClient.

Demonstrates the B0/B1/B3 end-to-end path and persistence without a live API
key. Not used for prompt tuning (docs/07 §9).

Usage: python3 scripts/dry_run_benchmark.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.benchmark import BenchmarkRunner  # noqa: E402
from app.config import Config  # noqa: E402
from app.llm_client import MockClient  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "tests"))
from conftest import make_wir, critique_json  # noqa: E402


def main() -> int:
    cases_path = REPO_ROOT / "benchmarks" / "smoke_cases.jsonl"
    cases = [json.loads(l) for l in open(cases_path, encoding="utf-8") if l.strip()]

    architect_outputs, writer_outputs = [], []
    for case in cases:
        wir = make_wir()
        wir["task"]["type"] = case["task_type"]
        wir["task"]["objective"] = case["instruction"][:60]
        architect_outputs.append(json.dumps(wir, ensure_ascii=False))
        writer_outputs.append(f"[dry-run draft for {case['id']}]\n\n{case['material']}")

    client = MockClient({
        "architect": architect_outputs,
        "writer": writer_outputs,
        "critic": [critique_json() for _ in cases],
        "baseline": [f"[{b} output for {c['id']}]" for c in cases for b in ("B0", "B1")],
    })

    config = Config.default()
    config.provider = "mock"
    runner = BenchmarkRunner(config, client=client)
    outcome = runner.run(cases_path, experiment_id="dry_run")
    print(json.dumps(outcome["summary"], ensure_ascii=False, indent=2))
    print(f"results: {outcome['dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
