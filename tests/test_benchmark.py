"""Smoke benchmark runner tests (mock provider)."""

from __future__ import annotations

from pathlib import Path

import json

from app.benchmark import BenchmarkRunner, load_cases
from app.llm_client import MockClient
from conftest import critique_json, make_critique, make_issue, wir_json


def write_cases(tmp_path):
    cases = [
        {"id": "T1", "task_type": "concept_essay", "material": "材料一",
         "instruction": "指令一", "target_length": 700},
        {"id": "T2", "task_type": "fiction_scene", "material": "材料二",
         "instruction": "指令二", "target_length": 800},
    ]
    path = tmp_path / "cases.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    return path


def test_load_public_synthetic_smoke_cases(repo_root):
    cases = load_cases(repo_root / "tests" / "fixtures" / "smoke_cases.jsonl")
    assert len(cases) == 10
    assert {c["task_type"] for c in cases} == {
        "narrative_commentary", "character_analysis", "fiction_scene",
        "concept_essay", "emotional_retelling",
    }


def test_benchmark_b0_b1_b3_end_to_end(tmp_path, tmp_config):
    cases_path = write_cases(tmp_path)
    # B3 PASS for both cases; B0/B1 direct generations.
    client = MockClient({
        "architect": [wir_json(), wir_json()],
        "writer": ["草稿一", "草稿二"],
        "critic": [critique_json(), critique_json()],
        "baseline": ["直接文本一", "直接文本二", "强提示文本一", "强提示文本二"],
    })
    runner = BenchmarkRunner(tmp_config, baselines_dir=Path(__file__).parent / "fixtures" / "baselines", client=client)
    outcome = runner.run(cases_path, baselines=("B0", "B1", "B3"),
                         experiment_id="test_exp")
    exp_dir = tmp_path / "results" / "test_exp"
    assert (exp_dir / "config.json").exists()
    assert (exp_dir / "outputs.jsonl").exists()
    assert (exp_dir / "judgments.jsonl").exists()
    assert (exp_dir / "summary.json").exists()
    assert (exp_dir / "pairwise_packets.jsonl").exists()
    assert (exp_dir / "pairwise_key.jsonl").exists()

    rows = [json.loads(l) for l in
            open(exp_dir / "outputs.jsonl", encoding="utf-8")]
    assert len(rows) == 6  # 2 cases x 3 baselines
    assert all(r["status"] == "success" for r in rows)

    summary = json.loads((exp_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["per_baseline"]["B3"]["success"] == 2
    assert summary["per_baseline"]["B0"]["success"] == 2

    # reproducibility fields
    cfg_info = json.loads((exp_dir / "config.json").read_text(encoding="utf-8"))
    assert cfg_info["case_ids"] == ["T1", "T2"]
    assert cfg_info["baseline_prompt_hashes"]["B0"]
    assert cfg_info["timestamp"]


def test_benchmark_persists_failed_case(tmp_path, tmp_config):
    cases_path = write_cases(tmp_path)
    client = MockClient({
        "architect": ["bad json", "still bad", wir_json()],
        "writer": ["草稿二"],
        "critic": [critique_json()],
        "baseline": ["t1", "t2", "t3", "t4"],
    })
    runner = BenchmarkRunner(tmp_config, baselines_dir=Path(__file__).parent / "fixtures" / "baselines", client=client)
    outcome = runner.run(cases_path, baselines=("B0", "B1", "B3"),
                         experiment_id="fail_exp")
    rows = [json.loads(l) for l in
            open(tmp_path / "results" / "fail_exp" / "outputs.jsonl",
                 encoding="utf-8")]
    b3_rows = [r for r in rows if r["baseline"] == "B3"]
    assert any(r["status"] == "failed" for r in b3_rows)


def test_benchmark_rejects_unknown_baseline(tmp_path, tmp_config):
    cases_path = write_cases(tmp_path)
    runner = BenchmarkRunner(tmp_config, baselines_dir=Path(__file__).parent / "fixtures" / "baselines", client=MockClient({}))
    try:
        runner.run(cases_path, baselines=("B9",))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_benchmark_builds_client_when_none_given(tmp_path, tmp_config):
    """Regression: direct baselines must not crash with client=None."""
    cases_path = write_cases(tmp_path)
    tmp_config.provider = "mock"
    runner = BenchmarkRunner(tmp_config, baselines_dir=Path(__file__).parent / "fixtures" / "baselines")  # no client passed
    assert runner.client is not None
    outcome = runner.run(cases_path, baselines=("B0",), experiment_id="no_client")
    rows = [json.loads(l) for l in
            open(tmp_path / "results" / "no_client" / "outputs.jsonl",
                 encoding="utf-8")]
    assert len(rows) == 2
    # bare MockClient has no queued responses -> failed rows, but never NoneType
    for r in rows:
        assert r["status"] == "failed"
        assert "NoneType" not in (r.get("error") or "")
