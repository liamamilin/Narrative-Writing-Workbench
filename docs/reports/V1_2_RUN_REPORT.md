# V1.2 Run Report — v1_2_clean Generation

Date: 2026-08-30. Experiment: `benchmarks/results/v1_2_clean/`
(10 smoke cases × 5 variant runs, shared WIR / shared-draft graph,
docs/16). Model: deepseek-v4-flash (all roles, pinned writer/architect role
configs). No blind pairwise results are interpreted here — this report
covers generation only.

## 1. Coverage

| metric | value |
|---|---|
| variant runs | 50 (+10 W0 alias rows = 60 output rows) |
| run failures | 0 |
| anonymous pairs packaged | 40 |
| byte-identical pairs (auto-tie) | 17 |
| pairs sent to manual blind review | 23 |
| pairs dropped (failed side) | 0 |

Manual sheet composition: A2_vs_A1 ×10 (H2), WGI_vs_W0 ×10 (H4),
A3_vs_A2 ×2 (H3, patched cases only), GI_A3_vs_WGI ×1 (H5, patched only).

## 2. Language-repair summary (docs/17)

- expected_language = zh declared explicitly on all 10 cases.
- **0 repairs needed**: every first Writer attempt was zh (attempts = 1 on
  all 50 rows; `language_repaired = False` everywhere; 0 functional
  failures).
- V1.1 comparison: A2 leaked zh→en in 4/10, A3 in 2/10. The Writer-boundary
  OUTPUT LANGUAGE directive eliminated leakage before review — no gate
  flips were needed to clean the corpus.

## 3. Hard gates (separate from literary quality)

- 60/60 gate rows, **0 functional failures** across all five checks
  (V1.1 ablation had 18).
- No fabricated quotations, no format leakage, all lengths inside
  [0.35×, 3×] target.

## 4. Critic behavior and cost (docs/16 §5)

| branch | PASS | PATCH_REQUIRED | patch rate |
|---|---|---|---|
| A3 (on A2 draft) | 8 | 2 | 20% |
| GI_A3 (on WGI draft) | 9 | 1 | 10% |
| total | 17 | 3 | 15% |

- Patcher invoked exactly once per PATCH_REQUIRED (3 calls), never on PASS;
  all 17 PASS branches shipped byte-identical drafts (auto-tied).
- Added cost of the Critic layer: 20 critic calls (~67.6k output tokens) +
  3 patch calls (~30.1k output tokens), ~969 s latency total
  (≈48 s per case-branch). Provider reported no monetary cost
  (`estimated_cost = 0`), so cost is tracked in tokens/latency.
- Post-review derived metrics (quality_gain_per_patch,
  quality_gain_per_extra_cost) will be computed in V1_2_ABLATION_REPORT.md
  once judgments are imported.

## 5. Length / budget (docs/18)

| variant | mean chars | median | min | max | mean len/target |
|---|---|---|---|---|---|
| A1 outline | 718 | 709 | 453 | 980 | 0.89 |
| A2 / W0 | 675 | 636 | 517 | 904 | 0.83 |
| A3 | 665 | 636 | 513 | 904 | 0.82 |
| WGI | 674 | 667 | 443 | 896 | 0.84 |
| GI_A3 | 662 | 667 | 443 | 896 | 0.82 |

WIR-driven text no longer over-expands relative to the outline baseline
(A2 −43 chars vs A1; V1.1 showed the opposite direction). All variants sit
slightly under target (~83–89%), uniformly — the budget mechanism is
backward compatible and did not differentially squeeze one arm.

## 6. Lineage spot-check

`NC_001:A3 → {"source_draft_id": "NC_001:A2", "critic_decision":
"PATCH_REQUIRED", "patched": true, "patch_targets": [...], "final_draft_id":
"NC_001:A3"}`; the Critic/Patcher inputs provably contain the exact A2
draft string (asserted by tests). CA_001 is the only case where both
branches were patched (A2 611→513, WGI 639→516 chars).

## 7. Commands

```
# generation (completed)
OPENAI_API_KEY=... OPENAI_BASE_URL=https://opencode.ai/zen/go/v1 \
python3 -m app.cli benchmark --cases benchmarks/smoke_cases.jsonl \
  --clean-ablation --experiment-id v1_2_clean --config config.live.yaml

# review sheet (exported; 23 manual pairs)
python3 scripts/review_txt.py export --results benchmarks/results/v1_2_clean

# after a reviewer returns the filled sheet
python3 scripts/review_txt.py import --results benchmarks/results/v1_2_clean \
  --file <filled>.txt --reviewer <name>
python3 -m app.cli report --results benchmarks/results/v1_2_clean --reviewer <name>
```

## 8. Blind review artifacts

- Sheet: `benchmarks/review_export/v1_2_clean_review.txt` (23 pairs,
  P01–P23, no system identity or mechanism wording — verified).
- Anon key (organizer-only): `benchmarks/review_export/v1_2_clean_anon_key.jsonl`.
- Auto-tie judgments already persisted in `judgments.jsonl`
  (reviewer `auto_tie`, 17 rows); `report --reviewer <name>` merges them
  deterministically.

**H2-clean / H3-clean / H4-confirm / H5 remain UNVALIDATED until blind
judgments are imported.** V1.2 stopping rule reached; no V2 / Pattern
Library work started.
