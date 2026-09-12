# V1_IMPLEMENTATION_REPORT.md

Completion report for Narrative Writing Harness V1, per `IMPLEMENTATION_TASK.md` Step 6.
Date: 2026-08-29.

## 1. Files Created

**Application (`app/`)**
- `__init__.py` — package marker, version.
- `config.py` — `Config`/`RoleConfig`/`DecisionThresholds`; YAML loading; per-role model, temperature, max tokens, timeout, structured mode; env-var key lookup. No model names in business logic.
- `prompts.py` — loads prompts verbatim from `/prompts`; sha256 version tracking.
- `schemas.py` — `SchemaSet` wrapping the supplied `wir/critique/run` JSON Schemas (source of truth); validation helpers returning structured error lists.
- `llm_client.py` — `LLMClient` ABC (`generate_text`, `generate_structured`); `OpenAIClient` (OpenAI-compatible, JSON-object mode with auto-fallback); `MockClient` (scripted, records all calls); `build_client`.
- `utils.py` — JSON extraction from model output (fence-tolerant), hashing, timestamps.
- `models.py` — `Usage`, `StageResult`, `RunResult`, `StructuredOutputError`.
- `structured.py` — shared generate → parse → validate → **one repair** flow (docs/01 §7).
- `architect.py`, `writer.py`, `critic.py`, `patcher.py` — the four agents.
- `persistence.py` — `RunStore` implementing the docs/09 run layout; best-effort writes; errors recorded, never raised.
- `pipeline.py` — single entry `run(material, instruction, task_type, constraints)`; run IDs; status; failure diagnostics.
- `benchmark.py` — smoke runner for B0/B1/B3 over `benchmarks/smoke_cases.jsonl`; persists `config.json`, `outputs.jsonl`, `judgments.jsonl`, `summary.json`, pairwise packets/key, diagnostics.
- `evaluation.py` — rule-based diagnostics; anonymous A/B pairwise packaging with hidden key; win-rate aggregation; optional LLM judge (config-gated).
- `review.py` — human blind-review loop (resumable), LLM judge driver, judgment aggregation report.
- `cli.py` — `python -m app.cli run|benchmark|review|judge|report`.
- `ui/` (isolated, optional) — Flask server + vanilla SPA for runs, benchmarks, and blind review (see §9).

**Supporting**
- `IMPLEMENTATION_REVIEW.md` (M0), `requirements.txt`, `config.example.yaml`, `scripts/dry_run_benchmark.py`.
- `tests/`: `conftest.py`, `test_schemas.py`, `test_prompts.py`, `test_config.py`, `test_architect.py`, `test_critic.py`, `test_pipeline.py`, `test_persistence.py`, `test_benchmark.py`, `test_evaluation.py`.

## 2. Architectural Decisions

- Plain-Python linear control flow in `Pipeline.run`; no orchestration framework (AGENTS.md constraint).
- Provider contract: `generate_structured` is best-effort JSON-object mode; **schema validation is authoritative**, provider-independent.
- **Critic decision authority**: the deterministic rule (fatal=0, major=0, moderate≤2, WQ≥24 — configurable thresholds) is recomputed from the validated critique and overrides a contradicting model-emitted `decision`; the mismatch is logged into `metadata.parameters.warnings` and `raw/errors.txt`. (Owner decision during M0 review.)
- **Spec deviation (smallest compatible fix)**: `metadata.json` follows the nested shape of `schemas/run.schema.json` (`models.*`, `parameters`, `usage.*`) rather than the flat sketch in `docs/09 §4`; per-role temperatures live in `parameters.temperatures`. Schemas are source of truth per AGENTS.md.
- WIR immutability: the parsed Architect output is passed byte-identical to Writer/Critic/Patcher prompts and to `wir.json` (verified by test).
- Patcher runs at most once, is never followed by another Critic call (verified by call-order test); preserve list + patch targets are explicitly embedded in its user message.
- `models.patcher` in metadata records the *configured* patcher model even when PASS skips the stage (run.schema requires it).
- Decision rule counts `issues` severities only (per docs/05 §7 wording); fidelity violations are surfaced separately in the critique.

## 3. Tests Executed and Results

Command: `python3 -m pytest tests/ -q` (Python 3.10.13, pytest 9.0.2, jsonschema 4.26.0)

**Result: 69 passed, 0 failed.**

Coverage of the 10 required test areas (Step 3):
1. valid WIR acceptance — `test_schemas.py::TestWIRSchema::test_valid_wir_accepted`
2. invalid WIR rejection — 8 negative WIR cases (missing fields, bad enums, bad ids, extra props, non-object)
3. valid critique acceptance — `test_schemas.py::TestCritiqueSchema::test_valid_critique_accepted`
4. invalid critique rejection — 6 negative critique cases
5. PASS skips Patcher — `test_pipeline.py::test_pass_skips_patcher` (asserts exact call sequence)
6. PATCH_REQUIRED calls Patcher exactly once — `test_pipeline.py::test_patch_required_calls_patcher_exactly_once`
7. run persistence — `test_persistence.py` (all docs/09 files, metadata schema-valid, run-id increment, persistence-failure never raises)
8. repair behavior — `test_architect.py` + `test_critic.py` (invalid→repair→valid; invalid×2 → `StructuredOutputError` with raw+errors persisted; repair prompt never guesses fields)
9. prompt file loading — `test_prompts.py`
10. configuration loading — `test_config.py`

Extras: decision-rule unit matrix (fatal/major/moderate/WQ/threshold-configurability/override), WIR immutability, benchmark end-to-end + failed-case persistence, evaluation packaging/aggregation.

## 4. Smoke Benchmark Status

- Runner implemented for `benchmarks/smoke_cases.jsonl` with **B0 Direct, B1 Strong Prompt, B3 WIR Workflow**.
- **LIVE benchmark executed** against an OpenAI-compatible gateway with `deepseek-v4-flash`
  (experiment `live_smoke_v2`, 2026-08-29): **10 cases x 3 baselines = 30/30 success.**
  - B3 mean Critic WQ: **28.8/30** (range 25-30); all 10 Critic decisions PASS
    (deterministic rule agreed with the model in every case).
  - Mean length: B0 1036 chars, B1 1072 chars, B3 1351 chars.
  - All outputs persisted: `benchmarks/results/live_smoke_v2/` (config.json, outputs.jsonl,
    judgments.jsonl, summary.json, pairwise_packets.jsonl [20 anonymous A/B packets],
    pairwise_key.jsonl, diagnostics.jsonl). B3 runs persisted in `runs/`.
- **Live repair path exercised**: run 000037's first Architect output failed schema
  validation (2 errors); the single repair attempt produced a valid WIR and the run succeeded.
- **Live Patcher path exercised** (run 000039, forced via stricter thresholds in
  `config.patch_demo.yaml`): Critic returned PATCH_REQUIRED with 3 specific issues
  (early_reveal, repetitive_contrast ×4 locations, perspective_deviation) and a 5-item
  preserve list; the Patcher changed only 8 diff lines while keeping the 6-paragraph
  structure — a local patch, not a regeneration.
- One live bug found and fixed: `BenchmarkRunner` did not construct a provider client when
  none was passed (B0/B1 crashed with `NoneType`); regression test added → 65 tests pass.
- Provider quirks handled: gateway stalls on `response_format: json_object` with reasoning
  models and defaults to runaway reasoning chains; live config uses
  `structured_mode: none` + `reasoning_effort: low` (docs/04 §7 fallback: JSON-only
  instruction + validation + one repair).
- Prompts were not tuned against benchmark outputs (docs/07 §9 respected).

## 5. Acceptance Checklist (docs/11)

Functional: **all 10 items satisfied**, including "at least 10 smoke benchmark cases run end-to-end" (live, 30/30 rows success).
Architecture: all 7 items satisfied (separation, externalized prompts/schemas, replaceable provider, no framework, WIR immutable, config-driven).
Quality: live inspection confirms WIR contains explicit reader-state transitions and drafts follow reveal timing; Critic issues are specific; preserve-list/patch behavior exercised live (run 000039: local 8-line patch, structure preserved).
Benchmark: outputs vs B0/B1 persisted + 20 anonymous pairwise packets generated; LLM-judge advisory pass completed (see §8); **human judgments pending** (required by docs/08 §8).
Research acceptance (H1–H3): requires the pending human pairwise review — data collection is complete.

## 6. Known Limitations

- Live path verified only against one OpenAI-compatible gateway/model (`deepseek-v4-flash`); other providers untested.
- Default thresholds let all 10 live drafts PASS (Critic self-agreement); the Patcher was exercised only via forced stricter thresholds (`config.patch_demo.yaml`). Real PATCH_REQUIRED frequency on the default model is low.
- The LLM judge (same model family as the generator) reported B3 *losing* overall to B0/B1 while winning on restraint — a textbook model-on-model style-preference artifact (docs/08 §8). This is advisory only and does NOT support or refute H1; human pairwise review is required before any effectiveness claim.
- Patcher minimality guard is a size-delta heuristic diagnostic, not a structural diff; over-editing is ultimately judged by the benchmark.
- Decision rule counts `issues` only; a fatal fidelity violation is expected to be co-reported as a fatal issue by the Critic prompt (docs/05 wording followed literally).
- `estimated_cost` stays 0.0 (gateway reports cost "0"; no price table in config).
- Long-context inputs are not chunked (V1 materials are short).
- Gateway intermittently stalls requests (observed 1–2 hangs per experiment); mitigated by 150 s timeout + 3 SDK retries.
- LLM judge implemented but config-gated (`judge_enabled: false` by default); human review flow is file-based (`pairwise_packets.jsonl` + `judgments.jsonl`).

## 7. Deviations from Specification

1. `metadata.json` nested per `run.schema.json` instead of flat per `docs/09 §4` sketch (schemas = source of truth; documented in IMPLEMENTATION_REVIEW §B.1).
2. Deterministic decision rule overrides the model's `decision` on contradiction (owner-approved resolution of an ambiguity in `IMPLEMENTATION_TASK` Critic requirements).
3. No other deviations; WIR concepts, enums, agent contracts, and patch protocol are implemented as specified.

## 8. Evaluation Workflow (concrete steps)

```bash
# 1. Human blind review (recommended; highest-confidence signal, docs/08 §4/§8).
#    Reviewers see only Text A / Text B; pairwise_key.jsonl stays hidden.
python3 -m app.cli review --results benchmarks/results/live_smoke_v2
#    Answer A/B/Tie for the 7 dimensions per pair; Ctrl-C pauses, rerun resumes.

# 2. (Optional) LLM judge as an advisory second signal.
python3 -m app.cli judge --results benchmarks/results/live_smoke_v2 --config config.live.yaml

# 3. Aggregate win rates -> judgment_summary.json
python3 -m app.cli report --results benchmarks/results/live_smoke_v2
```

Advisory LLM-judge run (same model family as generator; treat with caution per
docs/08 §8): B3 vs B0 overall 4W-6L; B3 vs B1 overall 1W-9L; B3 wins clearly on
restraint (9W-1L vs B0). B3 texts are ~30% longer; the judge appears to penalize
length/indirectness. **Human review remains required before claiming H1.**

Roadmap work (docs/13) stays out of scope until acceptance is decided on data.

## 9. Local Web UI (explicitly requested; docs/00 lists UI as a non-goal of the core system)

The UI lives entirely in `ui/` as an isolated read-mostly layer over persisted
artifacts — the core pipeline is unchanged (only `review.py` gained a `reviewer`
field so human and LLM judgments coexist). Flask is the sole added dependency
(`requirements-ui.txt`, optional).

```bash
pip3 install -r requirements-ui.txt          # once
python3 -m ui.server                          # http://127.0.0.1:8551
```

Views: 总览 (stats) · 运行记录 (per-run WIR timeline, critique, draft↔final diff) ·
新建运行 (pipeline in a background thread, stage stepper) · 基准评测 (dual-track
progress: human vs LLM) · 盲评工作台 (side-by-side A/B, 7-dimension segmented
controls, resumable) · 胜率报告 (human vs LLM tabs, per-dimension win-rate bars).

Tests: 70 passing (added dual-track review test).
