# V1.1 Ablation & Diagnostic Specification

Status: normative for V1.1. Scope: ablation + hard gates only. V2 (Pattern
Library) is explicitly out of scope (AGENTS.md non-goals).

## 1. Motivation

V1 blind review (live_smoke_v2) produced strong preliminary evidence that the
full workflow (B3) beats B0/B1, particularly on progression, meaning_density,
restraint, coherence. Two confounds remain unisolated, and immersion trails B1:

- Was the gain from Reader-State WIR, or simply from "planning before writing"?
- Did Critic + Patch add anything beyond WIR → Writer?
- Can immersion improve without regressing fidelity or restraint?

V1.1 answers these with controlled ablations. No hypothesis may be claimed
validated before benchmark + blind-review data exist.

## 2. Hypotheses

- **H2** Reader-State WIR improves writing compared with a conventional outline
  (test: A2 vs A1).
- **H3** Critic + Patch adds quality beyond WIR → Writer (test: A3 vs A2;
  patch frequency reported separately).
- **H4** Grounded Immersion improves immersion without sacrificing
  factual fidelity, restraint, meaning_density, or coherence
  (test: A2_GI vs A2, H3-extended check A3_GI vs A3 if run).

## 3. Variants

| ID | Architecture | Writer prompt | Critic | Patcher |
|---|---|---|---|---|
| B0 | direct prompt | — | no | no |
| B1 | strong prompt | — | no | no |
| A1 | conventional outline → writer | `writer_outline.md` | no | no |
| A2 | Reader-State WIR → writer | `writer.md` | no | no |
| A3 | Reader-State WIR → writer → critic → optional patch | `writer.md` | yes | ≤1 |
| A2_GI | Reader-State WIR → grounded-immersion writer | `writer_gi.md` | no | no |
| A3_GI | A2_GI + critic/patch (optional, not in default run) | `writer_gi.md` | yes | ≤1 |

A3 must be behaviorally identical to V1's B3 pipeline.

Controlled variables (docs/07 §reproducibility): same provider, same model for
all roles, same temperatures/max tokens as V1 live config, same 10 smoke cases,
single seed per stage. Architecture is the primary changing variable.

## 4. Conventional Outline Baseline (A1)

A1 is a deliberately strong, fair baseline. Outline (`schemas/outline.schema.json`,
`additionalProperties: false`) may contain:

- `thesis` / core idea
- ordered `sections` with `title`, `core_point`, `support` items drawn from material
- `opening` / `development` / `ending` roles, emphasis (详略), transition notes

It MUST NOT contain any reader-state modeling: no `reader_state`, knowledge/
belief/expectation transitions, question chains, reveal/conceal timing, or
explicit reader-state operators. Forbidden vocabulary is enforced by the schema
(property names) and checked by tests.

`writer_outline.md` mirrors `writer.md`'s craft rules (factual fidelity,
concrete-before-abstract, every-paragraph-moves, earned abstraction, anti-
pattern list) with WIR/rendering-of-beats/perspective-control sections removed,
so the only systematic difference from A2 is the structure representation.

## 5. Hard Fidelity Gates (deterministic, pre-quality)

Stored per output in `gates.jsonl` and in `outputs.jsonl` rows, separate from
literary-quality scores. A gate failure is a **functional failure**:

| Gate | Check (deterministic) |
|---|---|
| `expected_language_match` | instruction+material CJK ratio decides expected (zh/en); output language must match. Mismatch ⇒ functional failure. |
| `task_completion` | length within [0.35×, 3×] `target_length` (or ≥100 chars if unset); no refusal patterns (抱歉…无法 / I cannot / 作为AI). |
| `non_empty_output` | ≥30 characters after strip. |
| `factual_fidelity` | heuristic subset checks: every Arabic-digit group in output appears in material; every capitalized Latin token (outside stoplist) appears in material; every quote span >15 chars appears in material. Known limitation: CJK name extraction is not deterministic — documented, not checked. |
| `no_instruction_format_leakage` | output must not contain internal markers: `reader_state`, `start_state`, `end_state`, `wir_version`, `patch_targets`, `## Source Material`, `## Writing Instruction`, ```json, ``` fences, `Text A/B`, `rationale:`. |

`functional_failure = any gate failed`.

**Override rule**: in gate-adjusted aggregation, if a judgment's winner side
has `functional_failure`, that result counts as a loss for the winner
(reason `hard_gate`), because a text failing a hard gate must not win on prose
quality alone. Raw judgments are never mutated; both raw and adjusted views
are reported.

## 6. Pairwise Evaluation Packaging

Required anonymous pairs (existing 7 literary dimensions; A/B randomized,
identity hidden in `pairwise_key.jsonl`):

| Pair | Isolates |
|---|---|
| A2_vs_A1 | Reader-State WIR contribution (H2) |
| A3_vs_A2 | Critic/Patch contribution (H3) |
| A3_vs_B1 | full architecture vs strong single-pass prompting |
| A2_GI_vs_A2 | Grounded Immersion effect (H4) |

Blind review sheets contain only texts and the 7 dimensions. Gate results are
kept out of packets (they correlate with variant identity) and are joined only
at report time via the key.

## 7. Persistence

Under `benchmarks/results/<experiment_id>/`:

- `outputs.jsonl` — one row per case × variant: text, usage, `gates`, diagnostics
- `gates.jsonl` — gate rows joined to (case_id, variant)
- `artifacts/<case>_<variant>.json` — intermediate structure (outline / WIR) +
  stage usages for every variant that has one (A1/A2/A2_GI/A3)
- `pairwise_packets.jsonl`, `pairwise_key.jsonl`, `judgments.jsonl`,
  `diagnostics.jsonl`, `config.json`, `summary.json`

A3 additionally persists full pipeline runs under `runs/` (V1 behavior).

## 8. Case Set

The existing 10 smoke cases (`benchmarks/smoke_cases.jsonl`). Do not expand to
50 cases before the architecture signal survives ablation.

## 9. Stopping Rule

V1.1 ends with: implementation + tests green, 10-case ablation outputs
generated, blind-review packages produced, reports/V1_1_IMPLEMENTATION_REPORT.md and
reports/V1_1_ABLATION_REPORT.md written (the latter reports gates and package paths;
pairwise outcomes are interpreted only after human review). V2 Pattern Library
must not be started.
