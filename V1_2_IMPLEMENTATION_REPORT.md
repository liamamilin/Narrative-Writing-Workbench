# V1.2 Implementation Report — Clean Causal Ablation

Date: 2026-08-30. Scope: docs/16 (clean ablation), docs/17 (language
fidelity), docs/18 (beat budget). V2 / Pattern Library remain closed.

## 1. What was built

### 1.1 Expected-language contract + Writer-boundary repair (docs/17)

- `expected_language: zh | en | auto` added to config (`app/config.py`) and
  to the case contract; all 10 smoke cases now declare `zh` explicitly.
  Resolution priority case > config > heuristic
  (`app/gates.py:resolve_expected_language`); the language gate evaluates
  against the resolved value.
- All three writer prompts (`writer.md`, `writer_gi.md`,
  `writer_outline.md`) gained an Output Language rule; every writer user
  message now carries an explicit block:
  `OUTPUT LANGUAGE: Chinese` + "Write the complete final prose in Chinese.
  Do not switch to English even if internal representations, examples,
  schemas, or model reasoning contain English."
- `app/language.py:write_with_language_repair` implements the repair policy:
  immediate post-generation language check → on mismatch, exactly ONE
  regeneration with the same material/instruction/structure/writer policy
  plus an explicit Language Repair directive → still wrong ⇒
  `functional_failure`, sample excluded from Critic branching and its pairs
  are not packaged. The first failed generation is preserved
  (`original_text`). Persisted per row: `language_attempts`,
  `language_repaired`, `language_functional_failure`, `original_language`,
  `final_language`.
- Architect/WIR semantics untouched by the language fix.

### 1.2 Beat budget (docs/18)

- `schemas/wir.schema.json`: optional `task.target_length (int|null)` and
  optional per-beat `prose_budget: core|support|bridge`. Fully backward
  compatible (verified by schema tests).
- `prompts/architect.md`: Meaning-Gain/Word-Cost principle, prose_budget
  assignment guidance. `prompts/outline_architect.md`: same principle via
  the existing `emphasis` field (A1 fairness). All writer prompts: Length
  Budget section; user messages carry an `## Output Budget` block when
  `target_length` is set. No word-count enforcement code.

### 1.3 Shared-draft causal design (docs/16)

`app/variants.py:V12Runner` — per case:

```
one Architect call → ONE shared WIR ─┬→ W0 writer → D0 ─┬→ (control: A2 == W0 == D0)
                                     │                  └→ Critic(D0) → PASS: A3 = D0 byte-identical
                                     │                              → PATCH_REQUIRED: Patcher(≤1) → A3 = D1
                                     └→ WGI writer → GI_D0 → same Critic/Patch branch → GI_A3
outline architect → outline → writer_outline → A1
```

- **H2 (P1 A2_vs_A1)**: same writer role config, same language and
  target-length policy, same case, no Critic on either side.
- **H3 (P2 A3_vs_A2)**: A2/W0/D0 is ONE run (`V12_ALIAS {"W0": "A2"}`, alias
  row copy). Critic/Patcher receive the exact draft string; lineage
  persisted (`source_draft_id`, `critic_decision`, `patched`,
  `patch_targets`, `final_draft_id`).
- **H4 (P3 WGI_vs_W0)**: both writers consume the identical shared WIR.
- **H5 (P4 GI_A3_vs_WGI)**: branches from the exact GI draft.
- PASS ⇒ byte-identical ⇒ deterministic **auto-tie** (reviewer
  `auto_tie`), excluded from the manual sheet (docs/16 §6 option B);
  `report --reviewer X` merges auto-ties into X's totals.
- Cost metrics per patched-side row: `critic_calls`, `patch_calls`,
  critic/patch tokens + cost, `latency_added_seconds`; aggregated in
  `summary.json → v12.per_variant`.
- Hard gates unchanged and separate; pairs with a functional-failure side
  are dropped before packaging (repair failures surface before review).

### 1.4 CLI / review plumbing

- `benchmark --clean-ablation` (rows A1,A2,A3,WGI,GI_A3; pairs V12_PAIRS).
- `scripts/review_txt.py export` skips identical packets and states
  total / auto-tie / manual counts on the sheet.
- Fixed: `report --reviewer` was documented but not registered in the
  argparse subcommand (V1.1 gap).

## 2. Tests

`tests/test_clean_ablation.py`: 22 new tests covering the full docs/16 §9
acceptance list (language success/one-repair/functional-failure, repair
input equality, H2 setting equivalence, budget schema + bridge-merge
directive, shared WIR, same-draft branching H3/H5, PASS byte-identity,
Patcher gating/once, lineage + cost persistence, alias packaging,
auto-tie determinism, report merge, sheet exclusion, gate separation,
pair dropping on failure).

**Result: 106 passed** (84 V1/V1.1 tests unmodified and green + 22 new).

## 3. Fairness / validity notes

- W0's writing policy content is unchanged; only fidelity addenda
  (language, budget) were appended to prompts, per docs/17 §2 scope guard.
- All five writer-facing variants reuse the pinned `writer` role config;
  both architects reuse the pinned `architect` role config; one model
  (deepseek-v4-flash), temperature 0.7 writers / 0.2 architects.
- Architect usage is attributed to the A2 row (shared structures are
  generated once per case, not per variant).
- A3/GI_A3 PASS rows inherit the source draft's language fields; their
  final_language is re-detected on the shipped text.

## 4. Files

New: `app/language.py`, `tests/test_clean_ablation.py`,
`docs/16_V1_2_CLEAN_ABLATION_SPEC.md`,
`docs/17_LANGUAGE_AND_GENERATION_FIDELITY.md`,
`docs/18_BEAT_BUDGET_SPEC.md`.
Modified: `app/{gates,config,writer,variants,benchmark,review,cli,llm_client}.py`,
`prompts/{writer,writer_gi,writer_outline,architect,outline_architect}.md`,
`schemas/wir.schema.json`, `scripts/review_txt.py`,
`benchmarks/smoke_cases.jsonl` (explicit `expected_language: zh`).

Historical V1/V1.1 reports were not rewritten.

## 5. Run + review status

- Live 10-case generation: `benchmarks/results/v1_2_clean/`
  (see V1_2_RUN_REPORT.md for results, repair counts and gate summary).
- Blind review sheets: exported under `benchmarks/review_export/`.
- No pairwise interpretation is made in this report; hypotheses stay
  unvalidated until blind judgments are imported.
