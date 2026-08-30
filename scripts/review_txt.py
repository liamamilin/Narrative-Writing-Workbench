"""Export pairwise packets to a fill-in txt sheet, and import it back.

Usage:
    python3 scripts/review_txt.py export --results benchmarks/results/live_smoke_v2
    python3 scripts/review_txt.py import --results benchmarks/results/live_smoke_v2 \
        --file benchmarks/review_export/live_smoke_v2_filled.txt
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.review import DIMENSIONS, JUDGMENTS, PACKETS, KEY, load_jsonl  # noqa: E402

BLOCK = re.compile(r"^=== (\d+) (\S+) (\S+) ===$")


def export(results_dir: Path, out_dir: Path) -> Path:
    """Write an anonymous fill-in sheet. Pair labels are anonymized (P01..)
    so the sheet itself cannot leak system identities (docs/14 §6); the
    mapping goes to a separate *_anon_key.jsonl kept by the organizer.

    V1.2 deterministic policy (docs/16 §6): byte-identical pairs (auto-tie)
    are excluded from the manual review workload."""
    packets = load_jsonl(results_dir / PACKETS)
    if not packets:
        print(f"no packets in {results_dir}")
        sys.exit(1)
    identical = [p for p in packets if p.get("identical")]
    packets = [p for p in packets if not p.get("identical")]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{results_dir.name}_review.txt"
    anon_key = out_dir / f"{results_dir.name}_anon_key.jsonl"
    with anon_key.open("w", encoding="utf-8") as fh:
        for i, p in enumerate(packets, 1):
            fh.write(json.dumps({
                "label": f"P{i:02d}", "case_id": p["case_id"], "pair": p["pair"],
            }, ensure_ascii=False) + "\n")
    with path.open("w", encoding="utf-8") as fh:
        fh.write(
            "叙事盲评表 Blind Review Sheet\n"
            f"来源: {results_dir.name}   共 {len(packets)} 对(编号已匿名,不含系统信息)\n"
        )
        if identical:
            fh.write(
                f"另有 {len(identical)} 对两侧文本完全相同,"
                "已按确定性规则自动记为平手,无需人工评审。\n"
            )
        fh.write(
            "\n填写说明:每对文本在 7 个维度各填 A / B / T(平手),\n"
            "填在冒号后即可,不填的维度将被跳过。rationale 可写一句话。\n"
            "填完后把本文件发回,运行 import 命令即可入库。\n"
            + "=" * 60 + "\n"
        )
        for i, p in enumerate(packets, 1):
            fh.write(f"\n=== {i:02d} {p['case_id']} P{i:02d} ===\n\n")
            fh.write(f"--- Text A ({len(p['text_a'])} 字) ---\n{p['text_a']}\n\n")
            fh.write(f"--- Text B ({len(p['text_b'])} 字) ---\n{p['text_b']}\n\n")
            fh.write("--- 答案(填 A / B / T) ---\n")
            for d in DIMENSIONS:
                fh.write(f"{d}: ___\n")
            fh.write("rationale: \n")
    print(f"exported {len(packets)} pairs -> {path}")
    print(f"anon key (keep private, do not send to reviewers) -> {anon_key}")
    return path


def _pair_resolver(results_dir: Path, sheet_path: Path | None = None):
    """Map anonymous labels (P01..) back to real pairs via the anon key file.
    Search order: sheet's own directory, results dir, benchmarks/review_export."""
    candidates = []
    name = f"{results_dir.name}_anon_key.jsonl"
    if sheet_path:
        candidates.append(sheet_path.parent / name)
    candidates += [results_dir / name,
                   results_dir.parent.parent / "review_export" / name]
    mapping = {}
    for key_path in candidates:
        if key_path.exists():
            for row in load_jsonl(key_path):
                mapping[row["label"]] = (row["case_id"], row["pair"])
            break

    def resolve(case_id: str, token: str) -> tuple[str, str] | None:
        if token in mapping:
            c, pair = mapping[token]
            return (c, pair) if c == case_id else None
        return (case_id, token)
    return resolve


def import_sheet(results_dir: Path, file: Path, reviewer: str = "human") -> int:
    text = file.read_text(encoding="utf-8")
    text = re.sub(r"(=== \d{2} \S+ \S+ ===)", lambda m: "\n" + m.group(1) + "\n", text)
    resolve = _pair_resolver(results_dir, file)
    packets = {(p["case_id"], p["pair"]) for p in load_jsonl(results_dir / PACKETS)}
    judged = {(j.get("case_id"), j.get("pair"))
              for j in load_jsonl(results_dir / JUDGMENTS)
              if j.get("reviewer") == reviewer}
    judgments, current, buf = [], None, {}
    n_blocks = 0

    def flush():
        if current and buf:
            dims = {k: v for k, v in buf.items() if k in DIMENSIONS and v}
            if dims:
                case_id, pair = current
                if (case_id, pair) not in packets:
                    print(f"  skip {case_id}/{pair}: not in packets")
                elif (case_id, pair) in judged:
                    print(f"  skip {case_id}/{pair}: already judged")
                else:
                    judgments.append({
                        "case_id": case_id, "pair": pair,
                        "winner": ("Tie" if dims.get("overall") in ("T", "TIE")
                                   else dims.get("overall", "Tie")),
                        "dimensions": {k: ("Tie" if v in ("T", "TIE") else v)
                                       for k, v in dims.items()},
                        "rationale": buf.get("rationale", "").strip(),
                        "reviewer": reviewer,
                    })

    for line in text.splitlines():
        m = BLOCK.match(line.strip())
        if m:
            flush()
            n_blocks += 1
            current = resolve(m.group(2), m.group(3))
            if current is None:
                print(f"  skip block {m.group(1)}: unknown anon label")
            buf = {}
            continue
        if current:
            kv = re.match(r"^\s*(\w+)\s*[:：]\s*(\S.*)?$", line)
            if kv and (kv.group(1) in DIMENSIONS or kv.group(1) == "rationale"):
                val = (kv.group(2) or "").strip()
                if val and not set(val) <= {"_"}:
                    buf[kv.group(1)] = val.upper() if kv.group(1) in DIMENSIONS else val
    flush()

    if not judgments:
        print("no filled judgments found.")
        return 1
    with (results_dir / JUDGMENTS).open("a", encoding="utf-8") as fh:
        for j in judgments:
            fh.write(json.dumps(j, ensure_ascii=False) + "\n")
    print(f"parsed {n_blocks} blocks, imported {len(judgments)} judgments "
          f"(skipped {n_blocks - len(judgments)} empty/duplicate).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--results", required=True)
    e.add_argument("--out", default=str(ROOT / "benchmarks" / "review_export"))
    i = sub.add_parser("import")
    i.add_argument("--results", required=True)
    i.add_argument("--file", required=True)
    i.add_argument("--reviewer", default="human")
    args = ap.parse_args()
    if args.cmd == "export":
        export(Path(args.results), Path(args.out))
        return 0
    return import_sheet(Path(args.results), Path(args.file), args.reviewer)


if __name__ == "__main__":
    sys.exit(main())
