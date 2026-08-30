"""V1.2 clean causal ablation tests (docs/16 §9 checklist).

Covers: language repair policy, shared-draft H3/H5 lineage, shared-WIR
W0/WGI isolation, beat budget schema, auto-tie determinism, gate separation.
"""

from __future__ import annotations

import json

from app.benchmark import BenchmarkRunner
from app.gates import hard_gates, resolve_expected_language
from app.language import write_with_language_repair
from app.llm_client import MockClient
from app.variants import V12_ALIAS, V12_PAIRS, V12_ROWS, V12Runner
from conftest import critique_json, make_wir, outline_json, wir_json
from test_ablation import EN_TEXT, GOOD_ZH_TEXT, ZH_CASE

# Distinct zh texts per writer policy so mock runs are not accidentally equal.
OUTLINE_TEXT = "大纲路线的叙述:这段分析从结构入手,再回到细节收束。" * 12
GI_TEXT = "沉浸路线的叙述:录取通知书在抽屉里躺了五年,谁也没有再打开它。" * 10

PATCH_CRITIQUE = critique_json(
    decision="PATCH_REQUIRED",
    quality={"meaning_density": 3, "progression": 3, "immersion": 3,
             "specificity": 3, "restraint": 3, "coherence": 3},
    issues=[{"location": "B1", "severity": "moderate",
             "diagnosis": {"type": "over_explanation", "description": "d"},
             "effect": "e", "action": "a"},
            {"location": "B2", "severity": "major",
             "diagnosis": {"type": "flat_landing", "description": "d2"},
             "effect": "e2", "action": "a2"}],
    patch_targets=["B1", "B2"],
)


def _healthy_queue(**overrides) -> dict:
    """Mock queue for a clean all-PASS run of one case."""
    q = {
        "architect": [wir_json()],
        "outline_architect": [outline_json()],
        "writer_outline": [OUTLINE_TEXT],
        "writer": [GOOD_ZH_TEXT],
        "writer_gi": [GI_TEXT],
        "critic": [critique_json(), critique_json()],
    }
    q.update(overrides)
    return q


def _rows(tmp_config, queue) -> dict[str, dict]:
    client = MockClient(queue)
    rows = V12Runner(tmp_config, client=client).run_case(ZH_CASE)
    return {r["baseline"]: r for r in rows}, client


# ---- §2/§15.1-2: expected language + one repair --------------------------------

def test_expected_language_explicit_beats_heuristic():
    assert resolve_expected_language(ZH_CASE) == "zh"
    assert resolve_expected_language({**ZH_CASE, "expected_language": "en"}) == "en"
    assert resolve_expected_language({"instruction": "write in english",
                                      "material": "some facts"}, "zh") == "zh"


def test_writer_message_carries_output_language_directive(tmp_config):
    _, client = _rows(tmp_config, _healthy_queue())
    call = [c for c in client.calls if c["role"] == "writer"][0]
    user = call["messages"][1]["content"]
    assert "OUTPUT LANGUAGE: Chinese" in user
    assert "Do not switch to English even if internal representations" in user


def test_zh_writer_output_succeeds_without_repair(tmp_config):
    rows, client = _rows(tmp_config, _healthy_queue())
    a2 = rows["A2"]
    assert a2["status"] == "success"
    assert a2["language_attempts"] == 1
    assert a2["language_repaired"] is False
    assert [c for c in client.calls if c["role"] == "writer"].__len__() == 1


def test_en_output_triggers_exactly_one_repair(tmp_config):
    queue = _healthy_queue(writer=[EN_TEXT, GOOD_ZH_TEXT])
    rows, client = _rows(tmp_config, queue)
    a2 = rows["A2"]
    writer_calls = [c for c in client.calls if c["role"] == "writer"]
    assert len(writer_calls) == 2                      # exactly one repair
    assert a2["language_attempts"] == 2
    assert a2["language_repaired"] is True
    assert a2["original_language"] == "en"
    assert a2["final_language"] == "zh"
    assert a2["text"] == GOOD_ZH_TEXT
    assert "Language Repair" in writer_calls[1]["messages"][1]["content"]


def test_repair_uses_same_material_structure_and_policy(tmp_config):
    queue = _healthy_queue(writer=[EN_TEXT, GOOD_ZH_TEXT])
    _, client = _rows(tmp_config, queue)
    writer_calls = [c for c in client.calls if c["role"] == "writer"]
    m1, m2 = (c["messages"] for c in writer_calls)
    assert m1[0]["content"] == m2[0]["content"]        # same system prompt
    wir_json_str = json.dumps(make_wir(), ensure_ascii=False, indent=1)
    assert wir_json_str in m1[1]["content"] and wir_json_str in m2[1]["content"]
    assert ZH_CASE["material"] in m2[1]["content"]
    assert ZH_CASE["instruction"] in m2[1]["content"]
    assert writer_calls[0]["role_cfg"] == writer_calls[1]["role_cfg"]


def test_second_language_failure_becomes_functional_failure(tmp_config):
    queue = _healthy_queue(writer=[EN_TEXT, EN_TEXT])
    rows, client = _rows(tmp_config, queue)
    a2 = rows["A2"]
    assert a2["status"] == "failed"
    assert a2["error"] == "language_functional_failure"
    assert a2["text"] == EN_TEXT                       # never silently discarded
    assert a2["original_text"] == EN_TEXT
    assert a2["gates"]["checks"]["expected_language_match"] is False
    assert a2["gates"]["functional_failure"] is True
    # failed draft must NOT go to the Critic
    critic_calls = [c for c in client.calls if c["role"] == "critic"]
    assert all(EN_TEXT not in c["messages"][1]["content"] for c in critic_calls)
    assert rows["A3"]["status"] == "failed"
    assert "source draft unavailable" in rows["A3"]["error"]


# ---- §4: H2 clean comparison ----------------------------------------------------

def test_h2_a1_a2_use_equivalent_generation_settings(tmp_config):
    rows, client = _rows(tmp_config, _healthy_queue())
    a1_call = [c for c in client.calls if c["role"] == "writer_outline"][0]
    a2_call = [c for c in client.calls if c["role"] == "writer"][0]
    assert a1_call["role_cfg"] == a2_call["role_cfg"]  # pinned writer role config
    for call in (a1_call, a2_call):
        assert "OUTPUT LANGUAGE: Chinese" in call["messages"][1]["content"]
        assert f"{ZH_CASE['target_length']} characters" in call["messages"][1]["content"]
    assert rows["A1"]["status"] == rows["A2"]["status"] == "success"


# ---- §5: beat budget --------------------------------------------------------------

def test_beat_budget_schema_validation(schemas):
    assert schemas.validate_wir(make_wir()) == []      # backward compatible
    w = make_wir()
    w["task"]["target_length"] = 700
    w["beats"][0]["prose_budget"] = "core"
    w["beats"][1]["prose_budget"] = "bridge"
    assert schemas.validate_wir(w) == []
    bad = make_wir()
    bad["beats"][0]["prose_budget"] = "huge"
    assert schemas.validate_wir(bad)
    bad2 = make_wir()
    bad2["task"]["target_length"] = "long"
    assert schemas.validate_wir(bad2)


def test_bridge_beat_may_be_merged_directive(tmp_config, repo_root):
    rows, client = _rows(tmp_config, _healthy_queue())
    user = [c for c in client.calls if c["role"] == "writer"][0]["messages"][1]["content"]
    assert "bridge units get minimal prose and may be merged" in user
    assert "Meaning Gain" in user and "Word Cost" in user
    for name in ("writer.md", "writer_gi.md", "writer_outline.md"):
        text = (repo_root / "prompts" / name).read_text(encoding="utf-8")
        assert "Meaning Gain" in text and "bridge" in text
    arch = (repo_root / "prompts" / "architect.md").read_text(encoding="utf-8")
    assert "prose_budget" in arch and "Word Cost" in arch


# ---- §6: shared WIR for W0 vs WGI --------------------------------------------------

def test_wgi_and_w0_share_exactly_one_wir(tmp_config):
    rows, client = _rows(tmp_config, _healthy_queue())
    arch_calls = [c for c in client.calls if c["role"] == "architect"]
    assert len(arch_calls) == 1                        # one WIR per case
    assert rows["A2"]["structure"] == rows["WGI"]["structure"]
    assert rows["A2"]["structure"] == make_wir()


# ---- §4/§9: H3 / H5 same-draft branching -------------------------------------------

def test_h3_branches_from_exact_same_draft(tmp_config):
    rows, client = _rows(tmp_config, _healthy_queue())
    a2, a3 = rows["A2"], rows["A3"]
    critic_call = [c for c in client.calls if c["role"] == "critic"][0]
    assert a2["text"] in critic_call["messages"][1]["content"]
    assert a3["lineage"]["source_draft_id"] == a2["draft_id"]
    assert a3["lineage"]["final_draft_id"] == f"{ZH_CASE['id']}:A3"


def test_h5_branches_from_exact_same_gi_draft(tmp_config):
    rows, client = _rows(tmp_config, _healthy_queue())
    wgi, gi_a3 = rows["WGI"], rows["GI_A3"]
    gi_critic = [c for c in client.calls if c["role"] == "critic"][1]
    assert wgi["text"] in gi_critic["messages"][1]["content"]
    assert gi_a3["lineage"]["source_draft_id"] == wgi["draft_id"]


def test_pass_makes_output_byte_identical(tmp_config):
    rows, client = _rows(tmp_config, _healthy_queue())
    assert rows["A3"]["text"] == rows["A2"]["text"]
    assert rows["A3"]["patched"] is False
    assert rows["A3"]["lineage"]["critic_decision"] == "PASS"
    assert rows["GI_A3"]["text"] == rows["WGI"]["text"]
    patcher_calls = [c for c in client.calls if c["role"] == "patcher"]
    assert patcher_calls == []                         # PASS -> no patch, no regen


def test_patcher_only_on_patch_required_and_at_most_once(tmp_config):
    queue = _healthy_queue(
        critic=[PATCH_CRITIQUE, critique_json()],
        patcher=[GOOD_ZH_TEXT + "修补后的句子。", "不应被消费"],
    )
    rows, client = _rows(tmp_config, queue)
    patcher_calls = [c for c in client.calls if c["role"] == "patcher"]
    assert len(patcher_calls) == 1                     # only A3, exactly once
    assert rows["A3"]["patched"] is True
    assert rows["A3"]["lineage"]["critic_decision"] == "PATCH_REQUIRED"
    assert rows["A3"]["lineage"]["patch_targets"] == ["B1", "B2"]
    assert rows["A3"]["text"] == GOOD_ZH_TEXT + "修补后的句子。"
    assert rows["GI_A3"]["text"] == rows["WGI"]["text"]  # PASS side untouched
    # patcher input contains the exact source draft
    assert rows["A2"]["text"] in patcher_calls[0]["messages"][1]["content"]


def test_lineage_and_cost_persisted(tmp_config):
    rows, _ = _rows(tmp_config, _healthy_queue())
    a3 = rows["A3"]
    assert set(a3["lineage"]) == {"source_draft_id", "critic_decision",
                                  "patched", "patch_targets", "final_draft_id"}
    assert a3["cost"]["critic_calls"] == 1
    assert a3["cost"]["patch_calls"] == 0
    assert a3["cost"]["latency_added_seconds"] >= 0


# ---- §11/§12: benchmark packaging, alias, auto-tie ----------------------------------

def _v12_benchmark(tmp_path, tmp_config, **queue_overrides):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(ZH_CASE, ensure_ascii=False) + "\n", encoding="utf-8")
    client = MockClient(_healthy_queue(**queue_overrides))
    runner = BenchmarkRunner(tmp_config, client=client)
    outcome = runner.run(path, baselines=V12_ROWS,
                         experiment_id="v12_test", pairs=V12_PAIRS)
    exp = tmp_path / "results" / "v12_test"
    return outcome, exp, client


def test_v12_benchmark_rows_alias_and_pairs(tmp_path, tmp_config):
    outcome, exp, _ = _v12_benchmark(tmp_path, tmp_config)
    outputs = [json.loads(l) for l in
               (exp / "outputs.jsonl").read_text(encoding="utf-8").splitlines()]
    variants = [r["baseline"] for r in outputs]
    assert sorted(v for v in variants if not v.startswith("B")) == sorted(
        list(V12_ROWS) + ["W0"])
    w0 = [r for r in outputs if r["baseline"] == "W0"][0]
    a2 = [r for r in outputs if r["baseline"] == "A2"][0]
    assert w0["text"] == a2["text"] and w0["alias_of"] == "A2"

    packets = [json.loads(l) for l in
               (exp / "pairwise_packets.jsonl").read_text(encoding="utf-8").splitlines()]
    pairs = {p["pair"] for p in packets}
    assert pairs == {f"{s}_vs_{t}" for s, t in V12_PAIRS}
    keys = [json.loads(l) for l in
            (exp / "pairwise_key.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {(k["case_id"], k["pair"]) for k in keys} == \
           {(p["case_id"], p["pair"]) for p in packets}
    # WGI_vs_W0 packet sides resolve to the real variant names
    w0_key = [k for k in keys if k["pair"] == "WGI_vs_W0"][0]
    assert set(w0_key.values()) - {ZH_CASE["id"], "WGI_vs_W0"} == {"WGI", "W0"}


def test_identical_pairs_auto_tie_deterministically(tmp_path, tmp_config):
    outcome, exp, _ = _v12_benchmark(tmp_path, tmp_config)
    packets = [json.loads(l) for l in
               (exp / "pairwise_packets.jsonl").read_text(encoding="utf-8").splitlines()]
    identical = {p["pair"] for p in packets if p["identical"]}
    assert identical == {"A3_vs_A2", "GI_A3_vs_WGI"}   # both Critic PASS
    judgments = [json.loads(l) for l in
                 (exp / "judgments.jsonl").read_text(encoding="utf-8").splitlines()]
    ties = [j for j in judgments if j["reviewer"] == "auto_tie"]
    assert {t["pair"] for t in ties} == identical
    for t in ties:
        assert t["winner"] == "Tie"
        assert all(v == "Tie" for v in t["dimensions"].values())
    v12 = outcome["summary"]["v12"]
    assert v12["pairs"] == {"total": 4, "identical_auto_tie": 2, "manual_review": 2,
                            "dropped_failed_side": 0}
    assert v12["per_variant"]["A3"]["critic_pass"] == 1
    assert v12["per_variant"]["A3"]["patch_calls"] == 0


def test_auto_ties_merge_into_named_reviewer_report(tmp_path, tmp_config):
    from app.review import append_jsonl, write_report

    outcome, exp, _ = _v12_benchmark(tmp_path, tmp_config)
    # a named reviewer only judged the two differing pairs
    append_jsonl(exp / "judgments.jsonl", {
        "case_id": ZH_CASE["id"], "pair": "A2_vs_A1", "winner": "A",
        "dimensions": {d: "A" for d in
                       ("immersion", "progression", "meaning_density", "restraint",
                        "coherence", "naturalness", "overall")},
        "rationale": "", "reviewer": "tester"})
    report = write_report(exp, reviewer="tester")
    assert report["judgments"] == 3                    # 1 manual + 2 auto ties
    assert report["auto_ties_included"] == 2
    p2 = report["pairwise"]["A3_vs_A2"]["dimensions"]["overall"]
    assert p2["ties"] == 1                             # deterministic tie counted


def test_review_sheet_excludes_identical_pairs(tmp_path, tmp_config):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "review_txt", tmp_path / "unused.py")  # load real script instead
    from pathlib import Path as P
    script = P(__file__).resolve().parent.parent / "scripts" / "review_txt.py"
    spec = importlib.util.spec_from_file_location("review_txt", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    outcome, exp, _ = _v12_benchmark(tmp_path, tmp_config)
    sheet = mod.export(exp, tmp_path / "export")
    text = sheet.read_text(encoding="utf-8")
    assert text.count("=== 0") == 2                    # only the 2 differing pairs
    assert "另有 2 对" in text                          # identical pairs documented
    for word in ("Critic", "PASS", "patch", "A1", "A2", "A3", "WGI", "W0"):
        assert word not in text                        # no mechanism/identity leak


def test_hard_gates_stay_separate_from_literary_scores(tmp_path, tmp_config):
    outcome, exp, _ = _v12_benchmark(tmp_path, tmp_config)
    gates = [json.loads(l) for l in
             (exp / "gates.jsonl").read_text(encoding="utf-8").splitlines()]
    assert gates
    for g in gates:
        assert "quality" not in json.dumps(g)
        assert set(g["checks"]) == {"expected_language_match", "task_completion",
                                    "non_empty_output", "factual_fidelity",
                                    "no_instruction_format_leakage"}
    # gate record for the W0 alias exists so gated aggregation can look it up
    assert {g["variant"] for g in gates} >= {"A1", "A2", "A3", "WGI", "GI_A3", "W0"}


def test_language_repair_function_unit(tmp_config):
    """Direct unit test of the repair policy helper."""
    from app.writer import WriterAgent
    client = MockClient({"writer": [EN_TEXT, GOOD_ZH_TEXT]})
    writer = WriterAgent(client, tmp_config)
    res = write_with_language_repair(
        writer, material=ZH_CASE["material"], instruction=ZH_CASE["instruction"],
        structure=make_wir(), expected_language="zh", target_length=700)
    assert res.attempts == 2 and res.repaired and not res.functional_failure
    assert res.original_text == EN_TEXT
    assert res.to_row_fields()["language_repaired"] is True


def test_language_failure_side_drops_its_pairs(tmp_path, tmp_config):
    outcome, exp, _ = _v12_benchmark(
        tmp_path, tmp_config, writer=[EN_TEXT, EN_TEXT])
    v12 = outcome["summary"]["v12"]
    # A2 failed -> A2_vs_A1, A3_vs_A2, WGI_vs_W0 dropped; GI pair survives
    assert v12["pairs"]["dropped_failed_side"] == 3
    assert v12["pairs"]["total"] == 1
    packets = [json.loads(l) for l in
               (exp / "pairwise_packets.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [p["pair"] for p in packets] == ["GI_A3_vs_WGI"]


def test_language_repair_reset_signal(tmp_config):
    """on_delta sees a reset before the repair attempt re-streams."""
    from app.writer import WriterAgent
    client = MockClient({"writer": [EN_TEXT, GOOD_ZH_TEXT]})
    writer = WriterAgent(client, tmp_config)
    calls = []
    write_with_language_repair(
        writer, material=ZH_CASE["material"], instruction=ZH_CASE["instruction"],
        structure=make_wir(), expected_language="zh", target_length=700,
        on_delta=lambda d, r=False: calls.append((d, r)))
    assert ("", True) in calls
    reset_i = calls.index(("", True))
    assert not any(r for _, r in calls[:reset_i])          # clean first attempt
    assert any(d and not r for d, r in calls[reset_i + 1:])  # repair streams
