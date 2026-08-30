# 16 V1.2 Clean Causal Ablation Spec

Status: implemented. Depends on docs/14 (V1.1 ablation), docs/15 (Grounded
Immersion), docs/17 (language policy), docs/18 (beat budget).

## 1. Purpose

V1.1 produced three findings: (1) the full Harness keeps beating Strong
Prompt; (2) Grounded Immersion is a strong Writer-policy candidate; (3) H2/H3
were not causally clean because A2/A3 suffered zh→en language leakage and
A3/A2 were independent Writer samples (patch rate 1/10 could not isolate
Critic/Patch). V1.2 exists for exactly one reason: **clean causal
ablation**. V2 / Pattern Library remain closed.

## 2. Hypotheses

| ID | Statement | Pair |
|----|-----------|------|
| H2-clean | Reader-State WIR beats a strong conventional outline when both sides satisfy the same language/fidelity requirements | P1: A2 vs A1 |
| H3-clean | Critic + Patch improves a Writer draft when both conditions start from the EXACT SAME draft | P2: A3 vs A2 |
| H4-confirm | Grounded Immersion stays superior after leakage and sampling confounds are removed | P3: WGI vs W0 |
| H5 | On top of a GI Writer, Critic/Patch still adds enough value to justify its extra inference cost | P4: GI_A3 vs WGI |

No hypothesis may be claimed validated before blind review.

## 3. Experiment graph (per case)

```
Material + Instruction
 ├→ Outline Architect ─ outline ─→ writer_outline ──────────── A1
 └→ Architect ─ one shared WIR ─┬→ W0 (writer.md) ── D0 ═╗
                                │                        ╠═ P2: A3 vs A2
                                │   Critic(D0) ─ PASS ───╬→ A3 = D0 (byte-identical)
                                │            └ PATCH_REQ → Patcher → A3 = D1
                                │
                                └→ WGI (writer_gi.md) ─ GI_D0 ═╗
                                                               ╠═ P4: GI_A3 vs WGI
                                    Critic(GI_D0) ─ PASS ──────╬→ GI_A3 = GI_D0
                                                  └ PATCH_REQ → Patcher → GI_A3 = GI_D1
P1: A2 vs A1        P3: WGI vs W0 (same shared WIR, one Architect call)
```

Key rules:

1. **One WIR per case**, consumed by both W0 and WGI (docs §8): Writer
   policy is the only variable in P3.
2. **A2 == W0 == D0 is one single run** (`V12_ALIAS = {"W0": "A2"}`): the
   alias row is a copy of the same text/usage/gates, never a second sample.
3. **H3/H5 branch from the exact same draft string** — Critic and Patcher
   receive `source["text"]`, no regeneration on the control side (docs §6-§7).
4. PASS ⇒ D1 is byte-identical to D0. No forced changes; those pairs become
   deterministic ties (§6).
5. Language-functional failures never reach the Critic (docs/17 §3).
6. All writer variants share the pinned `writer` role config; both
   architects share the pinned `architect` role config; identical
   `expected_language` and `target_length` policy on every side.

## 4. Rows and pairs

Rows per case: `A1, A2, A3, WGI, GI_A3` (+ alias `W0`).
Pairs (`V12_PAIRS`): `(A2,A1) (A3,A2) (WGI,W0) (GI_A3,WGI)` → 40 anonymous
pairs on the 10 smoke cases. The 7 dimensions are unchanged (docs/08).

Lineage persisted on every patched-side row:

```json
"lineage": {"source_draft_id": "NC_001:A2", "critic_decision": "PASS|PATCH_REQUIRED",
            "patched": true, "patch_targets": [...], "final_draft_id": "NC_001:A3"}
```

plus `draft_id` on every writer row. The comparison key file lets the
organizer prove that both sides of P2/P4 share one source draft; packets
themselves stay anonymous and never reveal which side was patched.

## 5. Cost-aware Critic metrics

Each patched-side row carries `cost`: `critic_calls`, `patch_calls`,
critic/patch in/out tokens, `critic_cost`, `patch_cost`,
`latency_added_seconds`. `summary.json → v12.per_variant` aggregates PASS /
PATCH_REQUIRED counts, patch frequency and added latency. Post-review
reports compute `quality_gain_per_patch` (net wins ÷ patched cases) and
`quality_gain_per_extra_cost` (net wins ÷ added critic+patch calls) — the
question is "if Critic wins only rarely, is the extra API call worth it?"

## 6. Blind review and deterministic auto-tie

Policy chosen (option B, deterministic): **byte-identical pairs are
auto-recorded as all-dimension ties** (`reviewer: "auto_tie"`) in
`judgments.jsonl` and are **excluded from the manual review sheet**.
`scripts/review_txt.py export` skips packets flagged `identical` and states
the counts in the sheet header. `report --reviewer X` merges auto-ties into
X's aggregation unless X judged that pair manually. Raw judgments are never
mutated. Reports must show: total pairs, identical/PASS pairs, manually
reviewed differing pairs.

## 7. Hard gates

Unchanged from docs/14 §5 (five deterministic gates, stored separately,
gated aggregation reported separately). V1.2 priority: repair language
failures BEFORE review (docs/17) instead of relying on gate flips afterward.

## 8. CLI

```
python3 -m app.cli benchmark --cases benchmarks/smoke_cases.jsonl \
  --clean-ablation --experiment-id v1_2_clean --config config.live.yaml
python3 scripts/review_txt.py export --results benchmarks/results/v1_2_clean
python3 -m app.cli report --results benchmarks/results/v1_2_clean --reviewer <name>
```

## 9. Acceptance (implemented in tests/test_clean_ablation.py)

zh success without repair; en output triggers exactly one repair; second
failure ⇒ functional_failure (failed text preserved, Critic never sees it);
repair keeps material/instruction/structure/policy identical; A1/A2 equal
generation settings; W0/WGI share one WIR; H3/H5 branch from the same draft;
PASS ⇒ byte-identical; Patcher only on PATCH_REQUIRED and ≤ 1 call;
identical ⇒ deterministic auto-tie; beat-budget schema (optional, backward
compatible); bridge merge directive; gates separate from quality; lineage
persisted.

## 10. Stopping rule

Implementation + tests + 10-case generation + exported review sheets +
implementation/run reports. Then STOP: no blind-result interpretation
before review, no Pattern Library, no V2.
