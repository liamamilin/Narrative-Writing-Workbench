# V1.1 Implementation Report — Ablation & Diagnostics

Scope per docs/14_V1_1_ABLATION_SPEC.md and docs/15_GROUNDED_IMMERSION_SPEC.md.
No V2/Pattern-Library work. No hypothesis is claimed validated in this report;
pairwise interpretation waits for human blind review.

## 1. Changes Made

| File | Change |
|---|---|
| `docs/14_V1_1_ABLATION_SPEC.md` | NEW — normative V1.1 spec: variants, hard gates, pairing protocol, persistence, stopping rule |
| `docs/15_GROUNDED_IMMERSION_SPEC.md` | NEW — Grounded Immersion definition: licensed techniques, prohibitions, precedence, H4 evaluation rule |
| `app/gates.py` | NEW — deterministic hard fidelity gates (§2 below) |
| `app/outline.py` | NEW — `OutlineArchitectAgent` (A1 conventional outline, schema-validated, 1 repair) |
| `app/variants.py` | NEW — `VariantRunner` for A1 / A2 / A2_GI / A3 / A3_GI |
| `app/benchmark.py` | variants dispatch (B0,B1,A1,A2,A2_GI,A3,A3_GI,B3), gates on every row, `gates.jsonl`, `artifacts/`, configurable `pairs` |
| `app/evaluation.py` | `aggregate_judgments_gated()` — gate-failed side cannot win (raw judgments untouched) |
| `app/review.py` | `write_report()` gains reviewer filter + `pairwise_hard_gated` + `hard_failures` sections |
| `app/writer.py` | `prompt_file` + `structure_label` params; defaults byte-identical to V1 behavior |
| `app/schemas.py` | loads `outline.schema.json`, `validate_outline` |
| `app/pipeline.py` | optional shared `schemas` injection (no behavior change) |
| `app/cli.py` | `benchmark --ablation`; `report --reviewer` |
| `prompts/outline_architect.md` | NEW — strong conventional outline planner, explicit no-reader-state boundary |
| `prompts/writer_outline.md` | NEW — A1 writer: production craft rules minus WIR/reader-state sections |
| `prompts/writer_gi.md` | NEW — experimental Grounded-Immersion writer (docs/15) |
| `schemas/outline.schema.json` | NEW — `additionalProperties: false`; zero reader-state vocabulary (test-enforced) |
| `ui/` | benchmark page: per-variant stats + hard-gate table; `/summary`, `/gates` endpoints |
| `tests/test_ablation.py` | NEW — 14 tests (see §5) |

Production Writer prompt (`prompts/writer.md`) is **unchanged** (task §8).

## 2. Hard Fidelity Gates (`app/gates.py`)

Deterministic, pre-quality, stored per row in `outputs.jsonl[].gates` and
`gates.jsonl` — never merged into literary scores:

- `expected_language_match` — zh/en heuristic (CJK-vs-Latin ratio) on
  instruction+material vs output. Mismatch ⇒ functional failure.
- `task_completion` — length in [0.35×, 3×] target; refusal patterns fail.
- `non_empty_output` — ≥30 chars.
- `factual_fidelity` — output's Arabic-digit groups ⊆ material's; capitalized
  Latin tokens ⊆ material's (+stoplist); full-width quote spans >15 chars must
  appear in material. (ASCII quotes not checked — ambiguous pairing caused
  false positives, observed and fixed during live smoke.)
- `no_instruction_format_leakage` — internal markers (reader_state, ```json,
  "## Source Material", dimension names, …) must not appear.

`functional_failure = any gate failed`. In gate-adjusted aggregation a
gate-failing side is flipped to loss per dimension (`aggregate_judgments_gated`);
raw judgments are never mutated.

## 3. Variants Implemented

- **A1** outline_architect → writer_outline (outline schema forbids reader-state fields)
- **A2** architect(WIR) → writer; **no critic, no patcher** (test-enforced)
- **A2_GI** architect(WIR) → writer_gi (experimental, docs/15)
- **A3** == V1 B3 full pipeline (Architect→Writer→Critic→≤1 Patch)
- **A3_GI** implemented (writer swapped in pipeline) but **not in the default
  benchmark set** to keep runtime bounded; runnable via `--baselines A3_GI`.

Controlled variables: all variants share the live config's model and role
configs; outline architect reuses architect role settings; GI/outline writers
reuse writer role settings. Architecture is the primary changing variable.

## 4. Ablation Benchmark

```bash
# live run (executed; experiment id: ablation_v1_1)
OPENAI_API_KEY=... OPENAI_BASE_URL=... python3 -m app.cli benchmark \
  --cases benchmarks/smoke_cases.jsonl --ablation \
  --experiment-id ablation_v1_1 --config config.live.yaml

# mock dry-run (no API needed)
python3 scripts/dry_run_benchmark.py

# blind-review txt sheet for distribution
python3 scripts/review_txt.py export --results benchmarks/results/ablation_v1_1

# import filled sheets back (one per reviewer)
python3 scripts/review_txt.py import --results benchmarks/results/ablation_v1_1 \
  --file <filled>.txt --reviewer <name>

# reports (raw + hard-gate-adjusted; UI: #/report/ablation_v1_1)
python3 -m app.cli report --results benchmarks/results/ablation_v1_1 --reviewer <name>
```

Required pairs packaged: A2_vs_A1 (H2), A3_vs_A2 (H3), A3_vs_B1, A2_GI_vs_A2 (H4).

### Run status

`ablation_v1_1` COMPLETE: 60/60 rows generated (10 cases × 6 variants), 40
anonymous packets (A2_vs_A1, A3_vs_A2, A3_vs_B1, A2_GI_vs_A2), 60 artifacts,
`gates.jsonl` written. Hard-gate failures: B0 4, B1 5, A1 2, A2 4, A2_GI 1,
A3 2 (per-variant detail in V1_1_ABLATION_REPORT.md §2). A3 patch frequency
1/10. Blind-review sheet exported (anonymized labels). Pairwise outcomes await
human review; no hypothesis interpreted here.

## 5. Tests

`tests/test_ablation.py` — 14 new tests covering the task §10 checklist:
language-gate fail (zh case + en text) and pass; empty/refusal/leakage/
fabricated-fact gates; gate record separation from quality; outline schema
valid/invalid incl. sneaky `reader_state`/`reveal` injection rejected;
outline schema vocabulary scan (no reader-state words); A1 flow persists
outline & never calls critic; A2 never invokes critic/patcher; A2_GI uses the
GI prompt; A3 invokes critic; patcher at most once (with rule-precedence-
consistent PATCH_REQUIRED critique); full ablation benchmark end-to-end
(artifacts for every variant, gates.jsonl, all 4 pairs × cases, packet
anonymity: no side mapping in packets); gate-failed output cannot win
(summary hard_fail + `aggregate_judgments_gated` flip).

**Result: 84 passed, 0 failed** (70 V1 tests unchanged and green).

## 6. Known Limitations / Deviations

- `factual_fidelity` is heuristic: CJK person-name fabrication is NOT
  deterministically checkable without a segmenter (documented in docs/14 §5);
  ASCII quotation ambiguity is handled by only checking full-width quotes.
- `task_completion` is a proxy (length + refusal patterns), not semantic task
  verification. Critic fidelity remains the semantic layer.
- A1's outline prompt mentions forbidden terms as negative constraints; the
  data boundary itself is enforced by the closed schema (tests cover this).
- A3_GI implemented but excluded from the default run (spec: optional).
- Gate override flips apply at report/aggregation time only; packets and raw
  judgments are untouched.
- Language heuristic treats mixed text with ≥20% CJK as zh; edge cases (poetry
  with Latin titles) may misfire — flagged in gate record, not silently dropped.
