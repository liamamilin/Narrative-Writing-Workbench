"""Human/LLM pairwise review workflow.

Files (inside a benchmark results dir):
  pairwise_packets.jsonl  anonymous A/B texts (given to reviewers)
  pairwise_key.jsonl      side mapping (kept HIDDEN from reviewers)
  judgments.jsonl         reviewer answers, appended incrementally
  judgment_summary.json   aggregated win rates

Judgment record shape (matches app.evaluation.aggregate_judgments):
  {"case_id", "pair", "winner": "A|B|Tie",
   "dimensions": {"immersion": "A|B|Tie", ...}, "rationale": "..."}
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import Config
from .evaluation import DIMENSIONS, aggregate_judgments, llm_judge_pair
from .llm_client import LLMClient

PACKETS = "pairwise_packets.jsonl"
KEY = "pairwise_key.jsonl"
JUDGMENTS = "judgments.jsonl"
SUMMARY = "judgment_summary.json"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, obj: dict) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _done_set(judgments_path: Path, reviewer: str | None = None) -> set[tuple[str, str]]:
    js = load_jsonl(judgments_path)
    if reviewer is not None:
        js = [j for j in js if j.get("reviewer") == reviewer]
    return {(j["case_id"], j["pair"]) for j in js}


# ---- human interactive review -------------------------------------------------

_PROMPT_HINT = (
    "answer A / B / T(tie); Enter = T. Ctrl-C or 'q' to quit (progress saved)."
)


def review_interactive(results_dir: str | Path) -> int:
    results_dir = Path(results_dir)
    packets = load_jsonl(results_dir / PACKETS)
    if not packets:
        print(f"no packets found in {results_dir / PACKETS}")
        return 1
    judgments_path = results_dir / JUDGMENTS
    done = _done_set(judgments_path, reviewer="human")
    todo = [p for p in packets if (p["case_id"], p["pair"]) not in done]
    print(f"{len(done)} human-judged, {len(todo)} remaining. {_PROMPT_HINT}\n")

    for i, packet in enumerate(todo, 1):
        print("=" * 72)
        print(f"[{i}/{len(todo)}] case {packet['case_id']}  pair {packet['pair']}")
        print("-" * 28 + " Text A " + "-" * 28)
        print(packet["text_a"])
        print("-" * 28 + " Text B " + "-" * 28)
        print(packet["text_b"])
        print("-" * 72)
        dims: dict[str, str] = {}
        try:
            for dim in DIMENSIONS:
                raw = input(f"{dim:>16}? (A/B/T, Enter=Tie): ").strip().upper()
                if raw == "Q":
                    raise KeyboardInterrupt
                dims[dim] = {"A": "A", "B": "B"}.get(raw, "Tie")
            rationale = input("rationale (optional, Enter to skip): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nreview paused; resume later with the same command.")
            break
        judgment = {
            "case_id": packet["case_id"],
            "pair": packet["pair"],
            "winner": dims["overall"],
            "dimensions": dims,
            "rationale": rationale,
            "reviewer": "human",
        }
        append_jsonl(judgments_path, judgment)
        print(f"saved ({len(done) + i}/{len(packets)} total)\n")
    return 0


# ---- LLM judge (optional, config-gated) ---------------------------------------


def run_llm_judge(
    results_dir: str | Path,
    client: LLMClient,
    config: Config,
) -> int:
    results_dir = Path(results_dir)
    packets = load_jsonl(results_dir / PACKETS)
    if not packets:
        print(f"no packets found in {results_dir / PACKETS}")
        return 1
    judgments_path = results_dir / JUDGMENTS
    done = _done_set(judgments_path)
    todo = [p for p in packets if (p["case_id"], p["pair"]) not in done]
    print(f"{len(done)} judged, {len(todo)} to judge by LLM.")
    for i, packet in enumerate(todo, 1):
        try:
            judgment = llm_judge_pair(client, config, packet)
        except Exception as exc:
            print(f"[{i}/{len(todo)}] {packet['case_id']}/{packet['pair']}: FAILED {exc}")
            continue
        judgment["reviewer"] = "llm"
        append_jsonl(judgments_path, judgment)
        print(f"[{i}/{len(todo)}] {packet['case_id']}/{packet['pair']}: "
              f"winner={judgment['winner']} saved")
    return 0


# ---- aggregation ----------------------------------------------------------------


def write_report(results_dir: str | Path, reviewer: str | None = None) -> dict:
    results_dir = Path(results_dir)
    judgments = load_jsonl(results_dir / JUDGMENTS)
    auto_ties = [j for j in judgments if j.get("reviewer") == "auto_tie"]
    if reviewer is not None:
        judgments = [j for j in judgments if j.get("reviewer") == reviewer]
        # Deterministic V1.2 policy (docs/16 §6): byte-identical pairs are
        # auto-recorded as ties and excluded from the manual sheet; they are
        # merged into any reviewer's aggregation unless that reviewer already
        # judged the pair manually.
        covered = {(j["case_id"], j["pair"]) for j in judgments}
        judgments += [t for t in auto_ties
                      if (t["case_id"], t["pair"]) not in covered]
    key = load_jsonl(results_dir / KEY)
    if not judgments:
        report = {"judgments": 0, "reviewer": reviewer,
                  "note": "no judgments for this reviewer yet; run review or judge first"}
    else:
        from .evaluation import aggregate_judgments_gated
        report = {
            "judgments": len(judgments),
            "reviewer": reviewer,
            "auto_ties_included": (len(auto_ties) if reviewer is not None else 0),
            "pairwise": aggregate_judgments(judgments, key),
            "note": "LLM-judge results are advisory; human pairwise review is the "
                    "highest-confidence signal (docs/08 §8)."
                    if reviewer in (None, "llm") else
                    "Human pairwise review — highest-confidence signal (docs/08 §8).",
        }
        gates_path = results_dir / "gates.jsonl"
        if gates_path.exists():
            gate_rows = load_jsonl(gates_path)
            gates = {(g["case_id"], g["variant"]): g for g in gate_rows}
            report["pairwise_hard_gated"] = aggregate_judgments_gated(judgments, key, gates)
            report["hard_failures"] = [
                {"case_id": g["case_id"], "variant": g["variant"],
                 "reasons": g.get("failure_reasons", [])}
                for g in gate_rows if g.get("functional_failure")
            ]
    fname = SUMMARY if reviewer is None else f"judgment_summary_{reviewer}.json"
    (results_dir / fname).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report
