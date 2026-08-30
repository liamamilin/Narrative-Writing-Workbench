"""Evaluation layer tests: diagnostics, anonymous packaging, aggregation."""

from __future__ import annotations

from app.evaluation import (
    aggregate_judgments,
    build_pairwise_packets,
    rule_diagnostics,
)


def test_rule_diagnostics_flags_repetitive_contrast():
    text = "这不是失败，而是开始。\n不是结束，而是转折。\n真正的成长从来不是容易的。\n直到这一刻他懂了。\n或许吧。某种意义上。"
    diag = rule_diagnostics(text)
    assert "repeated_rhetorical_templates" in diag["flags"]
    assert diag["rhetorical_patterns"]["bushi_ershi"] >= 2


def test_rule_diagnostics_clean_text_no_flags():
    text = "父亲放下筷子。\n他问儿子存款够不够。\n儿子没有回答。"
    diag = rule_diagnostics(text)
    assert diag["flags"] == []


def test_pairwise_packets_are_anonymous_and_keyed():
    outputs = [
        {"case_id": "C1", "baseline": "B3", "text": "SYSTEMTEXT"},
        {"case_id": "C1", "baseline": "B0", "text": "B0TEXT"},
        {"case_id": "C1", "baseline": "B1", "text": "B1TEXT"},
    ]
    packets, key = build_pairwise_packets(outputs, seed=7)
    assert len(packets) == 2
    assert len(key) == 2
    for p, k in zip(packets, key):
        assert "baseline" not in p and "system" not in p  # no leakage
        assert k["a"] in ("B3", "B0", "B1") and k["b"] in ("B3", "B0", "B1")
        texts = {k["a"]: p["text_a"], k["b"]: p["text_b"]}
        assert texts["B3"] == "SYSTEMTEXT"


def test_aggregate_maps_through_key_despite_shuffle():
    outputs = []
    for i in range(4):
        outputs.append({"case_id": f"C{i}", "baseline": "B3", "text": "S"})
        outputs.append({"case_id": f"C{i}", "baseline": "B0", "text": "D"})
    packets, key = build_pairwise_packets(outputs, seed=3)
    judgments = []
    for k in key:
        # system always wins, whichever side it landed on
        system_side = "A" if k["a"] == "B3" else "B"
        judgments.append({
            "case_id": k["case_id"], "pair": k["pair"],
            "winner": system_side,
            "dimensions": {d: system_side for d in
                           ("immersion", "progression", "meaning_density",
                            "restraint", "coherence", "naturalness", "overall")},
        })
    summary = aggregate_judgments(judgments, key)
    pair = summary["B3_vs_B0"]
    assert pair["dimensions"]["overall"]["wins"] == 4
    assert pair["dimensions"]["overall"]["losses"] == 0
    assert pair["dimensions"]["overall"]["win_rate"] == 1.0
