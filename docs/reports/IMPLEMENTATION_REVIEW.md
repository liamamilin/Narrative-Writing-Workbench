# IMPLEMENTATION_REVIEW.md — Narrative Writing Harness V1

Milestone 0 deliverable per `docs/10_IMPLEMENTATION_PLAN.md`.
Frozen V1 implementation assumptions.

## A. System Understanding

NWH decomposes writing into explicit cognitive stages instead of one generation step:

```text
Input → Architect → WIR → Writer → Draft → Critic → (PASS → Final | PATCH_REQUIRED → Patcher → Final)
```

Stage responsibilities (per `docs/03_AGENT_CONTRACTS.md`):

| Stage | Input | Output | Notes |
|---|---|---|---|
| Architect | material + instruction + task constraints | schema-valid WIR | structured output; validate; ≤1 repair attempt |
| Writer | material + instruction + WIR | prose only | no redesign of WIR; priority: factual > WIR > reader-state > natural prose > style |
| Critic | material + instruction + WIR + draft | schema-valid critique | validate; ≤1 repair; PASS/PATCH_REQUIRED decision |
| Patcher | material + instruction + WIR + draft + critique | complete patched text | runs only when required; one pass; no recursive Critic |

Design principle ordering (AGENTS.md):
`meaning progression > reader-state fidelity > natural prose > stylistic decoration`

Critic decision rule (`docs/05_CRITIC_SPEC.md` §7): PASS iff fatal=0 AND major=0 AND moderate≤2 AND WQ≥24, where WQ = meaning_density + progression + immersion + specificity + restraint + coherence (max 30). Thresholds configurable.

Persistence (`docs/09_DATA_AND_RUN_FORMAT.md`): every run writes `runs/<run_id>/` with `input.json`, `wir.json`, `draft.md`, `critique.json`, `final.md`, `metadata.json`, and `raw/` diagnostics. Failed runs preserve raw invalid outputs and validation errors.

## B. Spec Consistency Review

1. **metadata.json shape conflict (resolved).** `docs/09` §4 sketches a *flat* metadata shape
   (`architect_model`, `writer_temperature`, `input_tokens`, …), while `schemas/run.schema.json`
   defines a *nested* shape (`models.{architect,writer,critic,patcher}`, `parameters`,
   `usage.{input_tokens,output_tokens,estimated_cost,latency_seconds}`, `patched`, `status`).
   Per AGENTS.md ("schemas are source of truth") and IMPLEMENTATION_TASK ("Use the supplied
   schemas as source of truth"), the implementation follows `run.schema.json`. The per-role
   temperatures from the doc sketch are stored inside `parameters`. This is the smallest
   compatible interpretation; no schema is modified.

2. **`models.patcher` required even on PASS (resolved).** `run.schema.json` requires all four
   model names; when the Critic returns PASS no Patcher call happens. Resolution: record the
   *configured* patcher model name regardless of use.

3. **Critic decision authority (resolved by owner decision).** If the model's emitted
   `decision` contradicts the deterministic rule computed from its own issues/scores,
   the **deterministic rule wins** and the mismatch is logged as a warning in run metadata
   diagnostics (`raw/decisions.txt`). The critique JSON stored is the model's validated
   output plus the corrected decision applied at pipeline level.

4. **Prompt spec vs prompt files.** `docs/04` requires prompts to state specific rules;
   the supplied `/prompts/*.md` already satisfy these. Prompts are loaded verbatim from
   files; production prompts are never embedded in Python (IMPLEMENTATION_TASK Step 2).

5. **WQ threshold ambiguity (minor).** §7 says "WQ >= 24" where WQ is the sum of the six
   quality dimensions (max 30). Implemented exactly as stated; configurable.

No contradiction blocks implementation.

## C. Proposed Code Structure

```text
app/
├── __init__.py
├── config.py        # Config + RoleConfig loading (yaml/env), decision thresholds; no hardcoded models
├── prompts.py       # load_prompt(role), content hash for version tracking
├── schemas.py       # load + validate against schemas/ (jsonschema); ValidationError surfacing
├── llm_client.py    # LLMClient ABC: generate_text / generate_structured; OpenAIClient; MockClient
├── models.py        # RunResult, Usage, StageOutput dataclasses
├── architect.py     # Architect: structured WIR, validate, ≤1 repair
├── writer.py        # Writer: prose only
├── critic.py        # Critic: structured critique, validate, ≤1 repair, decision rule
├── patcher.py       # Patcher: one-pass minimal patch
├── persistence.py   # RunStore: runs/<id>/ artifacts, raw/, errors.txt, failed-run diagnostics
├── pipeline.py      # run(material, instruction, task_type) → RunResult
├── benchmark.py     # smoke runner B0/B1/B3 → benchmarks/results/<exp>/
├── evaluation.py    # rule-based diagnostics, anonymous pairwise packaging, summary aggregation
└── cli.py           # python -m app.cli run | benchmark
tests/               # 10 required test areas, mock-based
```

## D. Milestone Plan (maps to docs/10)

- M0 — this review.
- M1 — skeleton, config loading, logging, requirements.txt.
- M2 — schema validation helpers + valid/invalid unit tests.
- M3 — LLM client abstraction (OpenAI-compatible concrete provider + Mock).
- M4 — Architect (prompt loading, structured WIR, validation, one repair, persistence hooks).
- M5 — Writer (WIR-aware prompt, prose output).
- M6 — Critic (fidelity, quality, anti-patterns, severity, preserve, patch targets, decision).
- M7 — Patcher (minimal patch prompt, preserve semantics, one pass).
- M8 — Pipeline (connect stages, run IDs, status handling).
- M9 — Persistence (all artifacts, failures preserved).
- M10 — Smoke benchmark runner over `benchmarks/smoke_cases.jsonl` (B0/B1/B3).
- M11 — Evaluation: result aggregation, anonymous pairwise packaging, summary (LLM judge behind config flag).
- M12 — Acceptance review vs `docs/11_ACCEPTANCE_CRITERIA.md`, V1_IMPLEMENTATION_REPORT.md.

## E. Technical Risks

| Risk | Mitigation |
|---|---|
| Invalid model JSON | strict validation + exactly one repair attempt; raw output + error persisted; run marked failed on second failure |
| Provider differences in structured output | `generate_structured` contract = JSON-object mode when supported, else JSON-only instruction; validation is provider-independent |
| Long context | smoke materials are short; per-role `max_output_tokens` from config; noted for V2 |
| Prompt/version tracking | prompt file name + sha256 recorded in metadata and raw diagnostics |
| Failed persistence | writes are best-effort with error capture; pipeline failure path always attempts to save raw outputs + errors.txt |
| Accidental full rewrite by Patcher | patch prompt + preserve list passed explicitly; diagnostics compute character-level change ratio and overlap with preserve targets |
| Critic decision inconsistency | deterministic rule recomputed and authoritative (owner decision); mismatch logged |
| No API key at test time | all tests use MockClient; live runs require OPENAI_API_KEY env |
