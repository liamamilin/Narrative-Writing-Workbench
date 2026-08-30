# 10 — Implementation Plan

## Milestone 0 — Specification Review

Before coding:

- read all required documents
- identify contradictions
- propose minimal corrections
- freeze V1 implementation assumptions

Deliverable:
`IMPLEMENTATION_REVIEW.md`

---

## Milestone 1 — Project Skeleton

Create:

```text
app/
prompts/
schemas/
benchmarks/
runs/
tests/
```

Add configuration loading and logging.

---

## Milestone 2 — Schemas

Implement:

- `wir.schema.json`
- `critique.schema.json`
- optional `run.schema.json`

Add validation helpers.

Unit-test valid and invalid examples.

---

## Milestone 3 — LLM Client Abstraction

Implement provider-neutral interface:

```python
generate_text(...)
generate_structured(...)
```

Support at least one concrete provider initially.

Keep role logic provider-independent.

---

## Milestone 4 — Architect

Implement:

- prompt loading
- structured WIR call
- validation
- one repair attempt
- persistence

Test against 3–5 simple inputs.

---

## Milestone 5 — Writer

Implement:

- WIR-aware prompt
- prose output
- factual/WIR constraints

Test whether reveal order follows WIR.

---

## Milestone 6 — Critic

Implement:

- fidelity audit
- quality scoring
- anti-pattern detection
- severity
- preserve list
- patch targets
- PASS/PATCH_REQUIRED decision

Critic output must validate against schema.

---

## Milestone 7 — Patcher

Implement:

- minimal patch prompt
- preserve semantics
- one-pass patching

Add tests ensuring unrelated text is not unnecessarily rewritten.

---

## Milestone 8 — Pipeline

Connect:

```text
Architect → Writer → Critic → optional Patcher
```

Add run IDs and status handling.

---

## Milestone 9 — Persistence

Persist all intermediate artifacts.

Store failures as well as successes.

---

## Milestone 10 — Smoke Benchmark

Create 10 cases.

Implement:

- B0 Direct
- B1 Strong Prompt
- B3 WIR Workflow

B2 Few-Shot may be added once examples are prepared.

---

## Milestone 11 — Evaluation

Implement:

- result aggregation
- anonymous pairwise packaging
- optional LLM judge
- summary output

---

## Milestone 12 — Acceptance Review

Run acceptance checklist from `11_ACCEPTANCE_CRITERIA.md`.

Do not start roadmap work before V1 is accepted.
