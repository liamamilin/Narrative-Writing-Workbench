"""V1.1 ablation tests: hard gates, variants, packaging (docs/14, §10 list)."""

from __future__ import annotations

import json

from app.benchmark import ABLATION_PAIRS, BenchmarkRunner
from app.gates import hard_gates
from app.llm_client import MockClient
from app.variants import VariantRunner
from conftest import (critique_json, make_critique, make_outline, outline_json,
                      wir_json)

ZH_CASE = {
    "id": "T1", "task_type": "concept_essay",
    "material": "母亲把录取通知书藏了五年,直到她去世后才被发现。",
    "instruction": "分析这种延迟揭示为什么有力量。不要增加新事实。",
    "target_length": 700,
}
GOOD_ZH_TEXT = "这段叙述的力量来自信息的不对称。" * 16  # 256 chars, zh, clean
EN_TEXT = ("The delayed reveal works because the reader reconstructs the "
           "mother's inner life after the fact, turning silence into an act "
           "of protection rather than concealment, and the daughter must "
           "re-read every childhood memory under this new light, which is "
           "why the structure feels inevitable in retrospect.")


# ---- 1/2: language gate ------------------------------------------------------

def test_english_output_on_zh_case_is_functional_failure():
    g = hard_gates(EN_TEXT, ZH_CASE)
    assert g["expected_language"] == "zh"
    assert g["actual_language"] == "en"
    assert g["checks"]["expected_language_match"] is False
    assert g["functional_failure"] is True


def test_chinese_output_passes_language_gate():
    g = hard_gates(GOOD_ZH_TEXT, ZH_CASE)
    assert g["checks"]["expected_language_match"] is True
    assert g["functional_failure"] is False
    assert g["failure_reasons"] == []


# ---- other gates ---------------------------------------------------------------

def test_gates_empty_refusal_leakage_and_fabricated_facts():
    assert hard_gates("", ZH_CASE)["checks"]["non_empty_output"] is False
    assert hard_gates("抱歉,作为AI我无法完成这个请求。" * 20,
                      ZH_CASE)["checks"]["task_completion"] is False
    leaked = hard_gates(GOOD_ZH_TEXT + "\n```json\n{\"reader_state\": 1}\n```",
                        ZH_CASE)
    assert leaked["checks"]["no_instruction_format_leakage"] is False
    fabricated = hard_gates(GOOD_ZH_TEXT + "他在1937年见过Michael。", ZH_CASE)
    assert fabricated["checks"]["factual_fidelity"] is False
    assert hard_gates(GOOD_ZH_TEXT, ZH_CASE)["checks"]["factual_fidelity"] is True


def test_gate_record_shape_separates_function_from_quality():
    g = hard_gates(GOOD_ZH_TEXT, ZH_CASE)
    assert set(g) == {"expected_language", "actual_language", "checks",
                      "functional_failure", "failure_reasons"}
    assert "quality" not in json.dumps(g)  # no literary score collapse


# ---- 3/4: outline schema + no reader state -----------------------------------

def test_outline_schema_valid_and_invalid(schemas):
    assert schemas.validate_outline(make_outline()) == []
    bad = make_outline()
    del bad["thesis"]
    assert schemas.validate_outline(bad)
    sneaky = make_outline()
    sneaky["reader_state"] = {"initial": "curious"}       # forbidden field
    assert schemas.validate_outline(sneaky)
    sneaky2 = make_outline()
    sneaky2["sections"][0]["reveal"] = ["fact"]           # forbidden field
    assert schemas.validate_outline(sneaky2)


def test_outline_schema_has_no_reader_state_vocabulary(repo_root):
    schema_text = (repo_root / "schemas" / "outline.schema.json").read_text()
    forbidden = ("reader_state", "knowledge", "belief", "expectation",
                 "question_chain", "reveal", "conceal", "end_state",
                 "start_state", "beat")
    for word in forbidden:
        assert word not in schema_text, f"outline schema mentions {word}"


# ---- 5/6/7: variant control flow ----------------------------------------------

def _runner(tmp_config, client):
    return VariantRunner(tmp_config, client=client)


def test_a1_uses_outline_and_no_reader_state(tmp_config):
    client = MockClient({
        "outline_architect": [outline_json()],
        "writer_outline": [GOOD_ZH_TEXT],
    })
    row = _runner(tmp_config, client).run(ZH_CASE, "A1")
    assert row["status"] == "success"
    assert row["structure"] == make_outline()
    roles = [c["role"] for c in client.calls]
    assert "critic" not in roles and "patcher" not in roles
    blob = json.dumps(row["structure"], ensure_ascii=False)
    for word in ("reader_state", "end_state", "start_state", "reveal"):
        assert word not in blob


def test_a2_never_invokes_critic(tmp_config):
    client = MockClient({
        "architect": [wir_json()],
        "writer": [GOOD_ZH_TEXT],
    })
    row = _runner(tmp_config, client).run(ZH_CASE, "A2")
    assert row["status"] == "success"
    roles = [c["role"] for c in client.calls]
    assert "critic" not in roles
    assert "patcher" not in roles


def test_a2_gi_uses_grounded_immersion_writer(tmp_config):
    client = MockClient({
        "architect": [wir_json()],
        "writer_gi": [GOOD_ZH_TEXT],
    })
    row = _runner(tmp_config, client).run(ZH_CASE, "A2_GI")
    assert row["status"] == "success"
    gi_calls = [c for c in client.calls if c["role"] == "writer_gi"]
    assert gi_calls
    system = gi_calls[0]["messages"][0]["content"]
    assert "Grounded" in system  # docs/15 prompt in effect


def test_a3_invokes_critic_and_passes_keep_draft(tmp_config):
    client = MockClient({
        "architect": [wir_json()],
        "writer": [GOOD_ZH_TEXT],
        "critic": [critique_json()],
    })
    row = _runner(tmp_config, client).run(ZH_CASE, "A3")
    assert row["status"] == "success"
    roles = [c["role"] for c in client.calls]
    assert "critic" in roles
    assert "patcher" not in roles   # PASS -> no patch
    assert row["patched"] is False


def test_a3_patch_at_most_once(tmp_config):
    def issue(loc):
        return {"location": loc, "severity": "moderate",
                "diagnosis": {"type": "over_explanation", "description": "d"},
                "effect": "e", "action": "a"}
    client = MockClient({
        "architect": [wir_json()],
        "writer": [GOOD_ZH_TEXT],
        "critic": [critique_json(
            decision="PATCH_REQUIRED",
            quality={"meaning_density": 3, "progression": 3, "immersion": 3,
                     "specificity": 3, "restraint": 3, "coherence": 3},
            issues=[issue("P1-S1"), issue("P2-S1")],
            patch_targets=["P1-S1", "P2-S1"],
        )],
        "patcher": [GOOD_ZH_TEXT + "修补后的句子。"],
    })
    row = _runner(tmp_config, client).run(ZH_CASE, "A3")
    assert row["status"] == "success"
    patch_calls = [c for c in client.calls if c["role"] == "patcher"]
    assert len(patch_calls) == 1
    assert row["patched"] is True


# ---- 8/9/10: benchmark integration --------------------------------------------

def _ablation_client():
    return MockClient({
        "baseline": ["基线文本一" + "好" * 260, "基线文本二" + "好" * 260,
                     "强提示文本一" + "好" * 260, "强提示文本二" + "好" * 260],
        "outline_architect": [outline_json(), outline_json()],
        "writer_outline": [GOOD_ZH_TEXT, GOOD_ZH_TEXT],
        "architect": [wir_json()] * 6,
        "writer": [GOOD_ZH_TEXT] * 4,
        "writer_gi": [GOOD_ZH_TEXT, GOOD_ZH_TEXT],
        "critic": [critique_json(), critique_json()],
    })


def test_ablation_benchmark_end_to_end(tmp_path, tmp_config):
    cases = [ZH_CASE,
             {**ZH_CASE, "id": "T2", "material": ZH_CASE["material"]}]
    path = tmp_path / "cases.jsonl"
    path.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n"
                            for c in cases), encoding="utf-8")
    runner = BenchmarkRunner(tmp_config, client=_ablation_client())
    outcome = runner.run(
        path, baselines=("B0", "B1", "A1", "A2", "A2_GI", "A3"),
        experiment_id="ablation_test", pairs=ABLATION_PAIRS)
    exp = tmp_path / "results" / "ablation_test"

    # every variant persists an artifact (docs/14 §7)
    for case in cases:
        for variant in ("B0", "B1", "A1", "A2", "A2_GI", "A3"):
            art = exp / "artifacts" / f"{case['id']}_{variant}.json"
            assert art.exists(), art
    a1 = json.loads((exp / "artifacts" / "T1_A1.json").read_text(encoding="utf-8"))
    assert a1["structure"]["outline_version"] == 1

    # gates stored separately, never inside literary scores
    assert (exp / "gates.jsonl").exists()
    gates_rows = [json.loads(l) for l in
                  (exp / "gates.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(gates_rows) == 12
    for row in gates_rows:
        assert row["functional_failure"] is False  # clean mock texts pass

    # required ablation pairs, identities hidden in packets
    packets = [json.loads(l) for l in
               (exp / "pairwise_packets.jsonl").read_text(encoding="utf-8").splitlines()]
    pairs = {(p["case_id"], p["pair"]) for p in packets}
    for case in cases:
        for sys_b, base_b in ABLATION_PAIRS:
            assert (case["id"], f"{sys_b}_vs_{base_b}") in pairs
    for p in packets:
        assert set(p) == {"case_id", "pair", "text_a", "text_b"}
        blob = json.dumps(p, ensure_ascii=False)
        assert '"a"' not in blob and '"b"' not in blob  # no side mapping

    # key file holds the mapping, separate from packets
    keys = [json.loads(l) for l in
            (exp / "pairwise_key.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(keys) == len(packets)
    assert all({"a", "b"} <= set(k) for k in keys)


def test_hard_failure_cannot_win_on_quality_alone(tmp_path, tmp_config):
    """A gate-failing side is flipped to loss in the gated aggregation."""
    cases = [ZH_CASE]
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(cases[0], ensure_ascii=False) + "\n", encoding="utf-8")
    client = MockClient({
        "baseline": [EN_TEXT, "强提示文本" + "好" * 260],
        "architect": [wir_json()],
        "writer": [GOOD_ZH_TEXT],
        "critic": [critique_json()],
    })
    runner = BenchmarkRunner(tmp_config, client=client)
    outcome = runner.run(path, baselines=("B0", "A3"),
                         experiment_id="gate_flip", pairs=(("A3", "B0"),))
    rows = {r["baseline"]: r for r in
            [json.loads(l) for l in (tmp_path / "results" / "gate_flip" /
                                     "outputs.jsonl").read_text(encoding="utf-8").splitlines()]}
    assert rows["B0"]["gates"]["functional_failure"] is True
    assert rows["A3"]["gates"]["functional_failure"] is False
    assert outcome["summary"]["per_baseline"]["B0"]["hard_fail"] == 1
    # literary quality fields unaffected by gate failure
    assert "quality" not in json.dumps(rows["B0"]["gates"])


def test_gated_aggregation_flips_winner():
    from app.evaluation import aggregate_judgments, aggregate_judgments_gated
    judgments = [{
        "case_id": "T1", "pair": "A2_vs_A1", "winner": "A",
        "dimensions": {d: "A" for d in
                       ("immersion", "progression", "meaning_density", "restraint",
                        "coherence", "naturalness", "overall")},
    }]
    key = [{"case_id": "T1", "pair": "A2_vs_A1", "a": "A1", "b": "A2"}]
    raw = aggregate_judgments(judgments, key)
    assert raw["A2_vs_A1"]["dimensions"]["overall"]["losses"] == 1  # A1 won raw
    gates = {("T1", "A1"): {"functional_failure": True}}
    gated = aggregate_judgments_gated(judgments, key, gates)
    # A1's raw win (side A) flips to A2
    assert gated["A2_vs_A1"]["dimensions"]["overall"]["wins"] == 1
    assert gated["A2_vs_A1"]["dimensions"]["overall"]["losses"] == 0
