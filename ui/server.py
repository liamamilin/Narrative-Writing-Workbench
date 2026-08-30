"""Narrative Writing Harness — local UI server (Flask).

Run from the project root:
    python3 -m ui.server            # http://127.0.0.1:8551
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"
BENCH_DIR = ROOT / "benchmarks" / "results"

app = Flask(__name__, static_folder="static", static_url_path="/static")

_lock = threading.Lock()


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


# ------------------------------------------------------------------ runs ----

_jobs: dict[str, dict] = {}


def _job_stage(d: Path) -> str:
    if (d / "final.md").exists():
        return "done"
    if (d / "draft.md").exists():
        return "critic"
    if (d / "wir.json").exists():
        return "writer"
    if (d / "input.json").exists():
        return "architect"
    return "starting"


@app.post("/api/runs")
def api_start_run():
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    body = request.get_json(force=True) or {}
    material = (body.get("material") or "").strip()
    instruction = (body.get("instruction") or "").strip()
    task_type = body.get("task_type") or "narrative_commentary"
    if not material or not instruction:
        return jsonify({"error": "material and instruction required"}), 400
    config_path = ROOT / "config.live.yaml"
    if not config_path.exists():
        config_path = ROOT / "config.example.yaml"

    def worker():
        try:
            from app.config import Config
            from app.pipeline import Pipeline
            cfg = Config.load(str(config_path))
            cfg.setup_logging()
            result = Pipeline(cfg).run(material, instruction, task_type)
            _jobs[job_id].update(done=True, ok=result.ok, run_id=result.run_id)
        except Exception as exc:  # noqa: BLE001
            _jobs[job_id].update(done=True, ok=False, error=str(exc))

    job_id = f"job-{threading.get_ident()}"
    _jobs[job_id] = {"done": False}
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.get("/api/runs/job/<job_id>")
def api_job_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "unknown job"}), 404
    out = dict(job)
    if job.get("run_id"):
        out["stage"] = _job_stage(RUNS_DIR / job["run_id"])
    elif job["done"]:
        out["stage"] = "failed"
    else:
        out["stage"] = "starting"
    return jsonify(out)


@app.get("/api/runs")
def api_runs():
    runs = []
    if RUNS_DIR.exists():
        for d in sorted(RUNS_DIR.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            meta = _read(d / "metadata.json") or {}
            crit = _read(d / "critique.json") or {}
            quality = crit.get("quality") or {}
            runs.append({
                "run_id": d.name,
                "status": meta.get("status", "unknown"),
                "patched": meta.get("patched"),
                "timestamp": meta.get("timestamp"),
                "decision": crit.get("decision"),
                "wq": sum(quality.values()) if quality else None,
                "has_final": (d / "final.md").exists(),
            })
    return jsonify({"runs": runs})


@app.get("/api/runs/<run_id>")
def api_run(run_id: str):
    d = RUNS_DIR / run_id
    if not d.is_dir():
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "run_id": run_id,
        "metadata": _read(d / "metadata.json"),
        "input": _read(d / "input.json"),
        "wir": _read(d / "wir.json"),
        "critique": _read(d / "critique.json"),
        "draft": _read_text(d / "draft.md"),
        "final": _read_text(d / "final.md"),
    })


# ------------------------------------------------------------ benchmark ----

@app.get("/api/benchmarks")
def api_benchmarks():
    out = []
    if BENCH_DIR.exists():
        for d in sorted(BENCH_DIR.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            packets = _load_jsonl(d / "pairwise_packets.jsonl")
            judgments = _load_jsonl(d / "judgments.jsonl")
            human = {(j.get("case_id"), j.get("pair")) for j in judgments
                     if j.get("reviewer") == "human"}
            llm = {(j.get("case_id"), j.get("pair")) for j in judgments
                   if j.get("reviewer") != "human"}
            pending = [p for p in packets
                       if (p.get("case_id"), p.get("pair")) not in human]
            out.append({
                "name": d.name,
                "packets": len(packets),
                "judged": len(human),
                "llm_judged": len(llm),
                "pending": len(pending),
                "summary": _read(d / "summary.json"),
            })
    return jsonify({"benchmarks": out})


@app.get("/api/benchmarks/<name>/packets")
def api_packets(name: str):
    d = BENCH_DIR / name
    if not d.is_dir():
        return jsonify({"error": "not found"}), 404
    packets = _load_jsonl(d / "pairwise_packets.jsonl")
    judgments = _load_jsonl(d / "judgments.jsonl")
    by_key: dict[tuple, dict] = {}
    for j in judgments:
        k = (j.get("case_id"), j.get("pair"))
        if j.get("reviewer") == "human" or k not in by_key:
            by_key[k] = j
    out = []
    for p in packets:
        k = (p.get("case_id"), p.get("pair"))
        j = by_key.get(k)
        out.append({
            "case_id": p.get("case_id"),
            "pair": p.get("pair"),
            "judged": bool(j and j.get("reviewer") == "human"),
            "llm_judged": bool(j and j.get("reviewer") != "human"),
            "judgment": j,
        })
    return jsonify({"packets": out})


@app.get("/api/benchmarks/<name>/packet")
def api_packet(name: str):
    """Return the next un-judged packet (or a specific one via ?case=&pair=)."""
    d = BENCH_DIR / name
    if not d.is_dir():
        return jsonify({"error": "not found"}), 404
    packets = _load_jsonl(d / "pairwise_packets.jsonl")
    judgments = _load_jsonl(d / "judgments.jsonl")
    done = {(j.get("case_id"), j.get("pair")) for j in judgments
            if j.get("reviewer") == "human"}
    want_case = request.args.get("case")
    want_pair = request.args.get("pair")
    for p in packets:
        if want_case and want_pair:
            if p.get("case_id") == want_case and p.get("pair") == want_pair:
                return jsonify({"packet": p, "index": packets.index(p),
                                "total": len(packets)})
            continue
        if (p.get("case_id"), p.get("pair")) not in done:
            return jsonify({"packet": p, "index": len(done),
                            "total": len(packets)})
    return jsonify({"packet": None, "done": True, "total": len(packets)})


@app.post("/api/benchmarks/<name>/judge")
def api_judge(name: str):
    d = BENCH_DIR / name
    if not d.is_dir():
        return jsonify({"error": "not found"}), 404
    body = request.get_json(force=True) or {}
    judgment = {
        "case_id": body.get("case_id"),
        "pair": body.get("pair"),
        "winner": body.get("dimensions", {}).get("overall", body.get("winner")),
        "dimensions": body.get("dimensions", {}),
        "rationale": body.get("rationale", ""),
        "reviewer": body.get("reviewer", "human"),
    }
    if not judgment["case_id"] or not judgment["pair"]:
        return jsonify({"error": "case_id and pair required"}), 400
    with _lock:
        jpath = d / "judgments.jsonl"
        existing = {(j.get("case_id"), j.get("pair"))
                    for j in _load_jsonl(jpath)
                    if j.get("reviewer") == "human"}
        if (judgment["case_id"], judgment["pair"]) in existing:
            return jsonify({"error": "already judged by human"}), 409
        with jpath.open("a", encoding="utf-8") as f:
            f.write(json.dumps(judgment, ensure_ascii=False) + "\n")
    return jsonify({"ok": True})


@app.get("/api/benchmarks/<name>/summary")
def api_summary(name: str):
    d = BENCH_DIR / name
    if not d.is_dir():
        return jsonify({"error": "not found"}), 404
    return jsonify(_read(d / "summary.json") or {})


@app.get("/api/benchmarks/<name>/gates")
def api_gates(name: str):
    d = BENCH_DIR / name
    rows = _load_jsonl(d / "gates.jsonl")
    per_variant: dict[str, dict] = {}
    for r in rows:
        e = per_variant.setdefault(r.get("variant", "?"),
                                   {"n": 0, "hard_fail": 0, "reasons": {}})
        e["n"] += 1
        if r.get("functional_failure"):
            e["hard_fail"] += 1
            for reason in r.get("failure_reasons", ["?"]):
                e["reasons"][reason.split(":")[0]] = \
                    e["reasons"].get(reason.split(":")[0], 0) + 1
    return jsonify({"per_variant": per_variant})


@app.get("/api/benchmarks/<name>/report")
def api_report(name: str):
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.review import write_report
    reviewer = request.args.get("reviewer")
    try:
        return jsonify(write_report(BENCH_DIR / name, reviewer=reviewer))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


# ------------------------------------------------------------------ pages ----

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


def main():
    port = 8551
    print(f"Narrative Writing Harness UI -> http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
