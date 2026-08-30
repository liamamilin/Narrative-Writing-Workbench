# V1.1 Ablation Report — Run Facts & Review Packages

Experiment: `ablation_v1_1` — 10 smoke cases × 6 variants (B0, B1, A1, A2,
A2_GI, A3), model `deepseek-v4-flash` via OpenAI-compatible gateway, config
`config.live.yaml`. Started 2026-08-29 22:27, completed 2026-08-30 00:48 (~2h21m).

**This report contains only deterministic run facts. No pairwise
interpretation is made: blind review packages are pending human judgment
(docs/08 §8). Hypotheses H2/H3/H4 remain unvalidated until then.**

## 1. Generation Status

- 60/60 rows generated successfully (0 provider failures; several transient
  500s absorbed by SDK retry; one Architect repair path exercised).
- Artifacts persisted: `benchmarks/results/ablation_v1_1/artifacts/` (60 files,
  outline/WIR structure + text + usage + gates per case × variant).
- A3 patch frequency: 1/10 PATCH_REQUIRED (9 PASS) — Critic self-agreement
  remains high on this model, as in V1.

## 2. Hard Fidelity Gates (deterministic; separate from literary quality)

Per-variant functional failures (`gates.jsonl`, 60 rows):

| Variant | hard_fail /10 | dominant reasons |
|---|---|---|
| B0 | 4 | fabricated long quotations (3), unsupported numerals (1) |
| B1 | 5 | fabricated long quotations (4), unsupported numerals (1) |
| A1 | 2 | length below floor (1), fabricated quotation (1) |
| A2 | 4 | **language mismatch zh→en (4)** + overlength |
| A2_GI | 1 | fabricated quotation (1) |
| A3 | 2 | **language mismatch zh→en (2)** + overlength |

Two functional findings (not literary judgments):

1. **Language leakage is a real WIR-pipeline failure mode.** The production
   Writer switched to English on 6/20 zh cases (4 in A2, 2 in A3; A2_GI 0).
   This was invisible in V1 (no gates) and would have let English text win on
   prose style. Under the docs/14 §5 override rule these outputs cannot win
   their pairs.
2. **Baselines fabricate quotations/dialogue** that the source material does
   not contain (B0/B1: 9 instances) — exactly the behavior Grounded Immersion
   forbids. A2_GI shows the lowest hard-fail rate of all variants (1/10).

Mean lengths (chars): B0 977 · B1 1082 · A1 657 · A2 2004 (inflated by the
English outliers) · A2_GI 762 · A3 1331.

## 3. Blind Review Packages

- Packets: `benchmarks/results/ablation_v1_1/pairwise_packets.jsonl` — 40
  anonymous A/B pairs: 10 × A2_vs_A1 (H2), 10 × A3_vs_A2 (H3),
  10 × A3_vs_B1, 10 × A2_GI_vs_A2 (H4).
- Hidden key: `benchmarks/results/ablation_v1_1/pairwise_key.jsonl`
  (organizer only).
- Distributable sheet (pair labels anonymized to P01–P40; verified to contain
  no variant names):
  `benchmarks/review_export/ablation_v1_1_review.txt`
- Label mapping (organizer only):
  `benchmarks/review_export/ablation_v1_1_anon_key.jsonl`

### Commands

```bash
# UI review (organizer machine)
python3 -m ui.server   # http://127.0.0.1:8551 -> 盲评工作台 -> ablation_v1_1

# offline: send the sheet, import each reviewer separately
python3 scripts/review_txt.py import \
  --results benchmarks/results/ablation_v1_1 \
  --file <reviewer_filled>.txt --reviewer <name>

# reports (raw + hard-gate-adjusted appear automatically)
python3 -m app.cli report --results benchmarks/results/ablation_v1_1 --reviewer <name>
```

## 4. Decision Rules Once Judgments Exist

Per docs/14 §5 / docs/15 §6, evaluate on the **hard-gate-adjusted** view:

- H2: A2_vs_A1 overall win-rate > 0.5 (and no hard-fail advantage for either
  side beyond the language leakage noted above).
- H3: A3_vs_A2 overall > 0.5; patch frequency reported separately (this run:
  10%, so A3_vs_A2 differences may be dominated by Critic selection rather
  than patching — note when interpreting).
- H4: A2_GI_vs_A2 immersion win-rate > 0.5 with restraint/meaning_density/
  coherence win-rates ≥ 0.4 and no increase in factual_fidelity gate failures
  (this run: GI 1/10 vs A2 4/10 hard fails — no regression signal so far).

## 5. Caveats

- Single reviewer family pending; all conclusions require ≥2 human reviewers.
- A2/A3 language failures mean some pairs are effectively "zh vs disqualified
  en" — gated aggregation will flip those, but reviewers will notice language
  differences. This is disclosed, not hidden.
- A3_GI variant implemented but not run (runtime budget).
