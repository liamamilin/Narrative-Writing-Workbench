import json
from pathlib import Path

import pytest

from scripts.product_human_review import (
    ReviewDataError,
    prepare_review,
    summarize_review,
)


def _write_inputs(tmp_path):
    cases = [
        {
            "id": "Q01",
            "criterion": "命题有推进",
            "input": {"input_mode": "topic_only", "topic": "旧钟"},
        },
        {
            "id": "D01",
            "criterion": "只修改指定段落",
            "input": {
                "input_mode": "draft_revision",
                "material": "第一段。\n\n说教的第二段。",
                "instruction": "删去说教",
            },
        },
    ]
    results = [
        {
            "case": "Q01",
            "mode": "topic_only",
            "criterion": "命题有推进",
            "status": "completed",
            "engine": "secret-model",
            "review_id": "review-secret",
            "operations": [{"automatic_decision": "PASS"}],
            "draft_before": "钟修好后仍留在抽屉里。",
        },
        {
            "case": "D01",
            "mode": "draft_revision",
            "criterion": "只修改指定段落",
            "status": "completed",
            "engine": "secret-model",
            "review_id": "review-secret-2",
            "operations": [{"automatic_decision": "PATCH_REQUIRED"}],
            "draft_before": "第一段。\n\n说教的第二段。",
            "draft_after": "第一段。\n\n第二段只留下动作。",
            "proposal": {"before": "说教的第二段。", "after": "第二段只留下动作。"},
        },
    ]
    cases_path = tmp_path / "cases.json"
    results_path = tmp_path / "results.json"
    cases_path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    results_path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    return cases_path, results_path


def _complete_ratings(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    data["reviewer"] = "Reviewer A"
    data["reviewed_at"] = "2026-09-13T15:00:00+08:00"
    for row in data["ratings"]:
        row["scores"] = {key: 4 for key in row["scores"]}
        row["comments"] = "独立判断"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_prepare_review_is_blind_reproducible_and_keeps_key_separate(tmp_path):
    cases, results = _write_inputs(tmp_path)
    packet_a = tmp_path / "packet-a"
    packet_b = tmp_path / "packet-b"
    key_a = tmp_path / "key-a.json"
    key_b = tmp_path / "key-b.json"

    first = prepare_review(results, cases, packet_a, key_a, "fixed-seed")
    second = prepare_review(results, cases, packet_b, key_b, "fixed-seed")

    assert first == second
    assert (packet_a / "REVIEW_PACKET.md").read_bytes() == (
        packet_b / "REVIEW_PACKET.md").read_bytes()
    assert (packet_a / "RATINGS.json").read_bytes() == (
        packet_b / "RATINGS.json").read_bytes()
    packet_text = (packet_a / "REVIEW_PACKET.md").read_text(encoding="utf-8")
    packet_files = "\n".join(
        path.read_text(encoding="utf-8") for path in packet_a.iterdir())
    assert "钟修好后仍留在抽屉里" in packet_text
    assert "secret-model" not in packet_files
    assert "PASS" not in packet_files
    assert "PATCH_REQUIRED" not in packet_files
    assert "Q01" not in packet_files
    assert "D01" not in packet_files
    assert {entry["case"] for entry in json.loads(key_a.read_text())["entries"]} == {
        "Q01", "D01"}

    with pytest.raises(ReviewDataError, match="目录之外"):
        prepare_review(results, cases, tmp_path / "nested-packet",
                       tmp_path / "nested-packet" / "key.json", "seed")


def test_summarize_requires_real_complete_scores_and_restores_case_ids(tmp_path):
    cases, results = _write_inputs(tmp_path)
    packet = tmp_path / "packet"
    key = tmp_path / "private-key.json"
    prepare_review(results, cases, packet, key, "fixed-seed")

    with pytest.raises(ReviewDataError, match="reviewer"):
        summarize_review(packet, key, None, tmp_path / "invalid-summary")

    _complete_ratings(packet / "RATINGS.json")
    summary = summarize_review(packet, key, None, tmp_path / "summary")

    assert summary["reviewer"] == "Reviewer A"
    assert summary["case_count"] == 2
    assert summary["overall_means"] == {
        "thesis_progression": 4.0,
        "defensibility": 4.0,
        "retention": 4.0,
        "patch_effect": 4.0,
    }
    assert {row["case"] for row in summary["ratings"]} == {"Q01", "D01"}
    report = (tmp_path / "summary" / "SUMMARY.md").read_text(encoding="utf-8")
    assert "Reviewer A" in report
    assert "Q01" in report
    assert "D01" in report


def test_summarize_rejects_placeholder_out_of_range_and_wrong_dimensions(tmp_path):
    cases, results = _write_inputs(tmp_path)
    packet = tmp_path / "packet"
    key = tmp_path / "private-key.json"
    prepare_review(results, cases, packet, key, "fixed-seed")
    _complete_ratings(packet / "RATINGS.json")
    ratings = json.loads((packet / "RATINGS.json").read_text(encoding="utf-8"))

    ratings["ratings"][0]["scores"][next(iter(ratings["ratings"][0]["scores"]))] = 6
    bad_score = tmp_path / "bad-score.json"
    bad_score.write_text(json.dumps(ratings, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ReviewDataError, match="1–5"):
        summarize_review(packet, key, bad_score, tmp_path / "bad-score-summary")

    _complete_ratings(packet / "RATINGS.json")
    ratings = json.loads((packet / "RATINGS.json").read_text(encoding="utf-8"))
    ratings["ratings"][0]["scores"]["unexpected"] = 3
    wrong_dimensions = tmp_path / "wrong-dimensions.json"
    wrong_dimensions.write_text(json.dumps(ratings, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ReviewDataError, match="评分维度"):
        summarize_review(packet, key, wrong_dimensions, tmp_path / "wrong-dim-summary")


def test_prepare_rejects_failed_or_mismatched_results(tmp_path):
    cases, results = _write_inputs(tmp_path)
    rows = json.loads(results.read_text(encoding="utf-8"))
    rows[0]["status"] = "failed"
    results.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ReviewDataError, match="未完成"):
        prepare_review(results, cases, tmp_path / "packet", tmp_path / "key.json", "seed")
