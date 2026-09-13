# IMPLEMENTATION_TASK.md

## Objective

Implement **Narrative Writing Harness V1** from the existing specifications.

Do not redesign the product.

The implementation target is:

```text
Input
→ Architect
→ WIR
→ Writer
→ Critic
→ optional Patcher
→ Final
```

## Step 0 — Read First

Read:

1. `AGENTS.md`
2. `docs/00_PROJECT_OVERVIEW.md`
3. `docs/12_THEORY.md`
4. `docs/01_ARCHITECTURE.md`
5. `docs/02_WIR_SPEC.md`
6. `docs/03_AGENT_CONTRACTS.md`
7. `docs/04_PROMPT_SPEC.md`
8. `docs/05_CRITIC_SPEC.md`
9. `docs/06_PATCH_PROTOCOL.md`
10. `docs/09_DATA_AND_RUN_FORMAT.md`
11. `docs/10_IMPLEMENTATION_PLAN.md`
12. `docs/11_ACCEPTANCE_CRITERIA.md`

Also inspect:

- `/prompts`
- `/schemas`
- `/benchmarks`

## Step 1 — Specification Review

Before writing implementation code, create:

`IMPLEMENTATION_REVIEW.md`

It must contain:

### A. System Understanding
Explain the pipeline and responsibility of each stage.

### B. Spec Consistency Review
List any contradictions, ambiguity, or fields that may cause implementation difficulty.

Do not silently resolve important contradictions.

Prefer the smallest compatible interpretation.

### C. Proposed Code Structure
Propose the exact files/modules to create.

### D. Milestone Plan
Map implementation work to `docs/10_IMPLEMENTATION_PLAN.md`.

### E. Technical Risks
At minimum consider:

- invalid model JSON
- provider differences in structured output
- long context
- prompt/version tracking
- failed persistence
- accidental full rewrite by Patcher
- Critic decision inconsistency

After writing `IMPLEMENTATION_REVIEW.md`, proceed unless a specification contradiction makes implementation impossible.

## Step 2 — Implement V1

Implementation requirements:

### Schemas
Use the supplied schemas as source of truth.

### Prompts
Load prompts from files. Do not embed production prompts directly in Python.

### LLM Interface
Provide a replaceable model client abstraction.

At minimum:

```python
generate_text(...)
generate_structured(...)
```

### Architect
- consume material + instruction
- produce WIR
- validate WIR
- make at most one repair attempt

### Writer
- consume material + instruction + WIR
- produce prose only

### Critic
- consume material + instruction + WIR + draft
- produce structured critique
- validate critique
- make at most one repair attempt
- compute or verify PASS/PATCH_REQUIRED decision consistently

### Patcher
- run only when required
- consume critique preserve list and patch targets
- produce complete patched text
- do not recursively call Critic

### Pipeline
Expose one simple entry point.

Suggested:

```python
result = pipeline.run(
    material=...,
    instruction=...,
    task_type=...,
)
```

Return an object containing:

- final text
- WIR
- draft
- critique
- patched flag
- run ID
- usage metadata

### Persistence
Persist all intermediate artifacts.

A failed run must also preserve useful diagnostics.

## Step 3 — Tests

Add tests for:

1. valid WIR acceptance
2. invalid WIR rejection
3. valid critique acceptance
4. invalid critique rejection
5. PASS skips Patcher
6. PATCH_REQUIRED calls Patcher exactly once
7. run persistence
8. missing/invalid structured output repair behavior
9. prompt file loading
10. configuration loading

Use mocks for LLM calls where appropriate.

## Step 4 — Smoke Benchmark

Implement a runner for:

`benchmarks/smoke_cases.jsonl`

Support at minimum:

- B0 Direct
- B1 Strong Prompt
- B3 WIR Workflow

Persist every output.

Do not optimize prompts based on benchmark outputs during the same run.

## Step 5 — CLI

Provide a minimal CLI.

Examples:

```bash
python -m app.cli run \
  --material-file example.txt \
  --instruction "重写为有叙述感的分析文字"
```

and:

```bash
python -m app.cli benchmark \
  --cases benchmarks/smoke_cases.jsonl
```

A UI is not required for this engine task. The product UI is specified
separately in `docs/narrative-writing-product-v0-spec/` (authoritative).

## Step 6 — Completion Report

When implementation is complete, create:

`V1_IMPLEMENTATION_REPORT.md`

Include:

- files created
- architectural decisions
- tests executed
- test results
- smoke benchmark status
- known limitations
- deviations from specification
- recommended next step

## Hard Constraints

Do not add:

- LangGraph
- CrewAI
- AutoGen
- RAG
- vector databases
- fine-tuning
- LoRA
- style extraction
- automatic pattern retrieval
- multi-round critique loops
- web UI (engine task only; superseded for the product layer by
  `docs/narrative-writing-product-v0-spec/`)

Do not rename or redefine WIR concepts without updating the corresponding specification and explaining why.

## Definition of Done

Do not claim completion merely because the pipeline can make model calls.

Completion requires satisfying `docs/11_ACCEPTANCE_CRITERIA.md`.
