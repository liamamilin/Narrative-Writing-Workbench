"""Evaluation layer (docs/08), V1 scope:

1. rule-based diagnostics (flags, not quality judges);
2. anonymous pairwise packaging (A/B with randomized assignment);
3. summary aggregation over judgments;
4. optional LLM pairwise judge (behind config flag; not run by default).
"""

from __future__ import annotations

import json
import logging
import random
import re
from collections import Counter

from .config import Config
from .llm_client import LLMClient

logger = logging.getLogger(__name__)

# Recurring rhetorical templates from docs/04 §4 and docs/05 §3.
RHYTHM_PATTERNS: dict[str, re.Pattern] = {
    "bushi_ershi": re.compile(r"不是[^。！？\n]{1,25}[，,]?而是"),
    "zhenzheng_conglaibushi": re.compile(r"真正[^。！？\n]{0,15}从来不是"),
    "zhidao_zheyike": re.compile(r"直到这一刻"),
    "ta_zhongyu_mingbai": re.compile(r"(?:他|她|我)终于明白"),
    "huoxu": re.compile(r"或许"),
    "mouzhongyiyi": re.compile(r"某种意义上"),
}
ABSTRACT_TERM_PATTERNS: dict[str, re.Pattern] = {
    "renxing": re.compile(r"人性"),
    "mingyun": re.compile(r"命运"),
    "linghun": re.compile(r"灵魂"),
    "ceng": re.compile(r"层次"),
}
TRANSITION_TERMS = ("然而", "因此", "不过", "其实", "事实上", "更重要的是")

SENT_SPLIT = re.compile(r"[。！？!?；;]")
PARA_SPLIT = re.compile(r"\n+")


def rule_diagnostics(text: str) -> dict:
    """Flag suspicious features. Diagnostic only, never a quality judgment."""
    rhetorical = {name: len(pat.findall(text)) for name, pat in RHYTHM_PATTERNS.items()}
    abstract = {name: len(pat.findall(text)) for name, pat in ABSTRACT_TERM_PATTERNS.items()}
    transitions = {t: text.count(t) for t in TRANSITION_TERMS}
    sentences = [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]
    lengths = sorted(len(s) for s in sentences)
    median_len = lengths[len(lengths) // 2] if lengths else 0
    extreme_long = sum(1 for n in lengths if n > 120)
    extreme_short = sum(1 for n in lengths if n <= 2)
    paragraphs = [p.strip() for p in PARA_SPLIT.split(text) if p.strip()]
    p_lens = [len(p) for p in paragraphs]
    uniform = False
    if len(p_lens) >= 4:
        mean = sum(p_lens) / len(p_lens)
        var = sum((x - mean) ** 2 for x in p_lens) / len(p_lens)
        stdev = var ** 0.5
        uniform = mean > 0 and (stdev / mean) < 0.15
    flags = []
    if sum(rhetorical.values()) >= 4:
        flags.append("repeated_rhetorical_templates")
    if uniform:
        flags.append("excessive_paragraph_uniformity")
    if extreme_long:
        flags.append("extreme_sentence_length")
    if abstract.get("renxing", 0) + abstract.get("mingyun", 0) >= 3:
        flags.append("repeated_abstract_terms")
    if sum(transitions.values()) >= 6:
        flags.append("repeated_transition_phrases")
    return {
        "rhetorical_patterns": rhetorical,
        "abstract_terms": abstract,
        "transition_counts": transitions,
        "sentence_median_len": median_len,
        "sentences_over_120_chars": extreme_long,
        "paragraph_count": len(paragraphs),
        "paragraph_uniformity": uniform,
        "flags": flags,
    }


# ---- anonymous pairwise packaging ----------------------------------------


def build_pairwise_packets(
    outputs: list[dict],
    target_baselines: tuple[str, ...] = ("B0", "B1"),
    system_baseline: str = "B3",
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    """Group outputs per case, pair system vs each baseline, randomly assign
    A/B so judges cannot infer which system produced which text.

    Returns (packets, key). The key file must be kept separate from packets.
    """
    rng = random.Random(seed)
    by_case: dict[str, dict[str, str]] = {}
    for row in outputs:
        by_case.setdefault(row["case_id"], {})[row["baseline"]] = row.get("text") or ""
    packets: list[dict] = []
    key: list[dict] = []
    for case_id, per_baseline in sorted(by_case.items()):
        for baseline in target_baselines:
            if system_baseline not in per_baseline or baseline not in per_baseline:
                continue
            texts = [(system_baseline, per_baseline[system_baseline]),
                     (baseline, per_baseline[baseline])]
            rng.shuffle(texts)
            (a_sys, a_text), (b_sys, b_text) = texts
            packets.append({
                "case_id": case_id,
                "pair": f"{system_baseline}_vs_{baseline}",
                "text_a": a_text,
                "text_b": b_text,
            })
            key.append({
                "case_id": case_id,
                "pair": f"{system_baseline}_vs_{baseline}",
                "a": a_sys,
                "b": b_sys,
            })
    return packets, key


# ---- judgment aggregation --------------------------------------------------

DIMENSIONS = ("immersion", "progression", "meaning_density", "restraint",
              "coherence", "naturalness", "overall")


def aggregate_judgments(judgments: list[dict], key: list[dict]) -> dict:
    """Win rates per pair and dimension, mapped back through the anonymity key."""
    key_map = {(k["case_id"], k["pair"]): k for k in key}
    stats: dict[str, dict[str, Counter]] = {}
    for j in judgments:
        pair_key = (j["case_id"], j["pair"])
        k = key_map.get(pair_key)
        if not k:
            continue
        system, baseline = pair_key[1].split("_vs_")
        side_of = {"A": k["a"], "B": k["b"]}
        winner_raw = j.get("winner", "Tie")
        dims = j.get("dimensions") or {d: winner_raw for d in DIMENSIONS}
        bucket = stats.setdefault(pair_key[1], {"system": system, "baseline": baseline,
                                                "dims": {d: Counter() for d in DIMENSIONS}})
        for dim in DIMENSIONS:
            w = dims.get(dim, "Tie")
            if w == "Tie":
                label = "tie"
            elif side_of.get(w) == system:
                label = "win"
            else:
                label = "loss"
            bucket["dims"][dim][label] += 1
    summary = {}
    for pair, bucket in stats.items():
        per_dim = {}
        for dim, counter in bucket["dims"].items():
            total = sum(counter.values()) or 1
            per_dim[dim] = {
                "wins": counter["win"],
                "losses": counter["loss"],
                "ties": counter["tie"],
                "win_rate": round(counter["win"] / total, 4),
            }
        summary[pair] = {"system": bucket["system"], "baseline": bucket["baseline"],
                         "dimensions": per_dim}
    return summary


def aggregate_judgments_gated(
    judgments: list[dict], key: list[dict], gates: dict[tuple[str, str], dict]
) -> dict:
    """Like aggregate_judgments, but a hard-gate failure overrides the literary
    winner (docs/14 §5): if the chosen side failed a gate, that dimension flips
    to the other side. Raw judgments are never mutated."""
    key_map = {(k["case_id"], k["pair"]): k for k in key}
    adjusted: list[dict] = []
    for j in judgments:
        k = key_map.get((j["case_id"], j["pair"]))
        if not k:
            continue
        side_of = {"A": k["a"], "B": k["b"]}
        other = {"A": "B", "B": "A"}
        jj = json.loads(json.dumps(j))
        flips = 0
        for dim, w in (jj.get("dimensions") or {}).items():
            system = side_of.get(w)
            if system and (gates.get((j["case_id"], system)) or {}).get("functional_failure"):
                jj["dimensions"][dim] = other.get(w, w)
                flips += 1
        if flips:
            jj["hard_gate_flips"] = flips
            jj["winner"] = (jj.get("dimensions") or {}).get("overall", jj.get("winner"))
        adjusted.append(jj)
    return aggregate_judgments(adjusted, key)


# ---- optional LLM judge (V1: stubbed behind config flag) -------------------

JUDGE_PROMPT = """You are an anonymous writing-quality judge.
Compare Text A and Text B for the stated questions. For each question answer exactly one of "A", "B", "Tie".
Return JSON only:
{{"immersion":"A|B|Tie","progression":"A|B|Tie","meaning_density":"A|B|Tie","restraint":"A|B|Tie","coherence":"A|B|Tie","naturalness":"A|B|Tie","overall":"A|B|Tie","rationale":"one or two sentences"}}

## Text A
{text_a}

## Text B
{text_b}
"""


def llm_judge_pair(client: LLMClient, config: Config, packet: dict) -> dict:
    """Run one anonymous pairwise LLM judgment. Only called when
    config.judge_enabled is true."""
    from .utils import parse_json_output

    messages = [
        {"role": "system", "content": "You are a careful, anonymous literary-quality judge."},
        {"role": "user", "content": JUDGE_PROMPT.format(
            text_a=packet["text_a"], text_b=packet["text_b"])},
    ]
    result = client.generate_text(
        messages, role="judge", role_cfg=config.role("critic")
    )
    try:
        obj = parse_json_output(result.text)
    except ValueError:
        logger.warning("judge output unparseable; recording tie")
        obj = {d: "Tie" for d in DIMENSIONS} | {"rationale": "unparseable judge output"}
    return {
        "case_id": packet["case_id"],
        "pair": packet["pair"],
        "winner": obj.get("overall", "Tie"),
        "dimensions": {d: obj.get(d, "Tie") for d in DIMENSIONS},
        "rationale": obj.get("rationale", ""),
    }
