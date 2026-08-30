"""Review workflow tests: resume behavior, LLM judge, report aggregation."""

from __future__ import annotations

import json

from app.config import Config
from app.llm_client import MockClient
from app.review import load_jsonl, review_interactive, run_llm_judge, write_report
from conftest import critique_json, wir_json

JUDGMENT = json.dumps(
    {"case_id": "C1", "pair": "B3_vs_B0", "winner": "A",
     "dimensions": {d: "A" for d in
                    ("immersion", "progression", "meaning_density", "restraint",
                     "coherence", "naturalness", "overall")},
     "rationale": "", "reviewer": "human"}, ensure_ascii=False)


def make_results(tmp_path):
    d = tmp_path / "results" / "exp1"
    d.mkdir(parents=True)
    packets = [
        {"case_id": "C1", "pair": "B3_vs_B0", "text_a": "aaa", "text_b": "bbb"},
        {"case_id": "C1", "pair": "B3_vs_B1", "text_a": "aaa", "text_b": "ccc"},
    ]
    keys = [
        {"case_id": "C1", "pair": "B3_vs_B0", "a": "B3", "b": "B0"},
        {"case_id": "C1", "pair": "B3_vs_B1", "a": "B1", "b": "B3"},
    ]
    with open(d / "pairwise_packets.jsonl", "w", encoding="utf-8") as fh:
        for p in packets:
            fh.write(json.dumps(p) + "\n")
    with open(d / "pairwise_key.jsonl", "w", encoding="utf-8") as fh:
        for k in keys:
            fh.write(json.dumps(k) + "\n")
    return d


def test_human_review_skips_already_judged(tmp_path, monkeypatch, capsys):
    d = make_results(tmp_path)
    (d / "judgments.jsonl").write_text(JUDGMENT + "\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": "Q")
    review_interactive(d)
    out = capsys.readouterr().out
    # only the second packet should have been shown
    assert "B3_vs_B1" in out
    assert "B3_vs_B0" not in out
    assert len(load_jsonl(d / "judgments.jsonl")) == 1


def test_llm_judgment_does_not_block_human_review(tmp_path, monkeypatch, capsys):
    d = make_results(tmp_path)
    llm = json.loads(JUDGMENT)
    llm["reviewer"] = "llm"
    (d / "judgments.jsonl").write_text(
        json.dumps(llm, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": "Q")
    review_interactive(d)
    out = capsys.readouterr().out
    # human review must still offer the LLM-judged pair (dual track)
    assert "2 remaining" in out
    assert "B3_vs_B0" in out


def test_llm_judge_appends_and_resumes(tmp_path):
    d = make_results(tmp_path)
    cfg = Config.default()
    client = MockClient({
        "judge": ['{"immersion":"A","progression":"B","meaning_density":"Tie",'
                  '"restraint":"A","coherence":"A","naturalness":"B",'
                  '"overall":"A","rationale":"r"}']
    })
    run_llm_judge(d, client, cfg)
    rows = load_jsonl(d / "judgments.jsonl")
    assert len(rows) == 1  # second packet failed (queue empty) and was skipped
    assert rows[0]["case_id"] == "C1"
    run_llm_judge(d, MockClient({}), cfg)  # resume: nothing left for first packet
    assert len(load_jsonl(d / "judgments.jsonl")) == 1


def test_report_aggregates_through_key(tmp_path):
    d = make_results(tmp_path)
    with open(d / "judgments.jsonl", "w", encoding="utf-8") as fh:
        # C1/B3_vs_B0: a=B3, judge picks A -> B3 wins
        fh.write(json.dumps({"case_id": "C1", "pair": "B3_vs_B0", "winner": "A",
                             "dimensions": {k: "A" for k in
                                            ("immersion", "progression", "meaning_density",
                                             "restraint", "coherence", "naturalness",
                                             "overall")}}) + "\n")
        # C1/B3_vs_B1: a=B1, judge picks B -> B3 wins (B side is B3)
        fh.write(json.dumps({"case_id": "C1", "pair": "B3_vs_B1", "winner": "B",
                             "dimensions": {k: "B" for k in
                                            ("immersion", "progression", "meaning_density",
                                             "restraint", "coherence", "naturalness",
                                             "overall")}}) + "\n")
    report = write_report(d)
    assert report["judgments"] == 2
    pw = report["pairwise"]
    assert pw["B3_vs_B0"]["dimensions"]["overall"]["wins"] == 1
    assert pw["B3_vs_B1"]["dimensions"]["overall"]["wins"] == 1
    assert (d / "judgment_summary.json").exists()


def test_report_empty_judgments(tmp_path):
    d = make_results(tmp_path)
    report = write_report(d)
    assert report["judgments"] == 0
