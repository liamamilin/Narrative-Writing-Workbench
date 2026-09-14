import json
from pathlib import Path

import pytest

from scripts.product_human_review import (
    ReviewDataError,
    prepare_review,
    prepare_review_v2,
    summarize_review,
    summarize_review_v2,
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


def _write_v2_inputs(tmp_path):
    cases = [
        {"id": "Q01", "criterion": "角度应具体并能推进",
         "input": {"input_mode": "topic_only", "topic": "旧钟"}},
        {"id": "S01", "criterion": "不添加材料之外的事实",
         "input": {"input_mode": "source_grounded", "material": "钟在抽屉里。",
                    "instruction": "写出理解的距离"}},
        {"id": "D01", "criterion": "只改善指定段落",
         "input": {"input_mode": "draft_revision", "material": "第一段。\n\n说教。",
                    "instruction": "删去说教"}},
    ]
    candidates = [{
        "id": f"internal-angle-{index}", "label": f"角度 {index}",
        "mechanism": f"机制 {index}", "core_question": f"问题 {index}",
        "deep_meaning": f"含义 {index}", "boundary": f"边界 {index}",
        "reader_end_state": f"收获 {index}",
    } for index in range(1, 4)]
    results = [
        {"case": "Q01", "mode": "topic_only", "criterion": "角度应具体并能推进",
         "status": "completed", "engine": "secret", "draft_before": "钟留在抽屉里。",
         "angle_options": {"candidates": candidates}},
        {"case": "S01", "mode": "source_grounded", "criterion": "不添加材料之外的事实",
         "status": "completed", "engine": "secret", "draft_before": "钟没有被拿出来。"},
        {"case": "D01", "mode": "draft_revision", "criterion": "只改善指定段落",
         "status": "completed", "engine": "secret", "draft_before": "第一段。\n\n说教。",
         "draft_after": "第一段。\n\n动作。",
         "proposal": {"before": "说教。", "after": "动作。"}},
    ]
    cases_path, results_path = tmp_path / "cases.json", tmp_path / "results.json"
    cases_path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    results_path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    return cases_path, results_path


def _complete_v2_ratings(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    data["reviewer"] = "Reviewer B"
    data["reviewed_at"] = "2026-09-14T10:00:00+08:00"
    for row in data["ratings"]:
        row["scores"] = {key: 4 for key in row["scores"]}
        if row["kind"] == "angle_set":
            row["preferred_candidate"] = "C02"
        row["comments"] = "逐项核对"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_v2_packet_covers_angles_and_keeps_private_candidate_ids_out(tmp_path):
    cases, results = _write_v2_inputs(tmp_path)
    packet, key = tmp_path / "packet", tmp_path / "private-key.json"
    manifest = prepare_review_v2(results, cases, packet, key, "fixed-seed")

    assert manifest["schema_version"] == 2
    assert manifest["kind_counts"] == {"draft": 2, "angle_set": 1, "patch": 1}
    packet_text = "\n".join(path.read_text(encoding="utf-8")
                              for path in packet.iterdir() if path.suffix in {".md", ".json"})
    assert "Q01" not in packet_text and "internal-angle-1" not in packet_text
    assert "C01" in packet_text and "C03" in packet_text
    private = json.loads(key.read_text(encoding="utf-8"))
    angle = next(item for item in private["items"] if item["kind"] == "angle_set")
    assert angle["candidate_map"] == {
        "C01": "internal-angle-1", "C02": "internal-angle-2", "C03": "internal-angle-3"}


def test_v2_summary_restores_selected_angle_and_separates_dimensions(tmp_path):
    cases, results = _write_v2_inputs(tmp_path)
    packet, key = tmp_path / "packet", tmp_path / "private-key.json"
    prepare_review_v2(results, cases, packet, key, "fixed-seed")
    _complete_v2_ratings(packet / "RATINGS.json")
    summary = summarize_review_v2(packet, key, None, tmp_path / "summary")

    assert summary["schema_version"] == 2
    assert summary["case_count"] == 3 and summary["item_count"] == 4
    assert {row["kind"] for row in summary["ratings"]} == {"draft", "angle_set", "patch"}
    angle = next(row for row in summary["ratings"] if row["kind"] == "angle_set")
    assert angle["preferred_candidate"] == "C02"
    assert angle["preferred_candidate_id"] == "internal-angle-2"
    assert summary["kinds"]["patch"]["means"] == {
        "target_improvement": 4.0, "context_preservation": 4.0,
        "scope_control": 4.0}
    assert "internal-angle-2" in (tmp_path / "summary" / "SUMMARY.md").read_text(encoding="utf-8")


def test_v2_requires_a_preferred_angle_and_rejects_wrong_dimensions(tmp_path):
    cases, results = _write_v2_inputs(tmp_path)
    packet, key = tmp_path / "packet", tmp_path / "private-key.json"
    prepare_review_v2(results, cases, packet, key, "fixed-seed")
    _complete_v2_ratings(packet / "RATINGS.json")
    ratings = json.loads((packet / "RATINGS.json").read_text(encoding="utf-8"))
    angle = next(row for row in ratings["ratings"] if row["kind"] == "angle_set")
    angle["preferred_candidate"] = "C99"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(ratings, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ReviewDataError, match="preferred_candidate"):
        summarize_review_v2(packet, key, bad, tmp_path / "bad-summary")
