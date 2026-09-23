# AGENTS.md

This repository is specification-first.

## Authority (updated 2026-08-30)

The **Product V0 spec** at `docs/narrative-writing-product-v0-spec/` is the
current authoritative specification for the product layer and is now the
active work track. It supersedes any "no UI" statements in older documents.
The engine (`app/`) is complete through V1.2; engine documents below remain
authoritative for engine internals only.

Before implementing code, read:

1. `docs/narrative-writing-product-v0-spec/README.md`
2. `docs/narrative-writing-product-v0-spec/AGENTS.md`
3. `docs/narrative-writing-product-v0-spec/PRODUCT_IMPLEMENTATION_TASK.md`
4. `docs/narrative-writing-product-v0-spec/product/00..10` (in order)

For Quick Write (topic-only) work, the **V0.1 extension** at
`docs/narrative-writing-product-v0.1-quick-write-spec/` extends — not
replaces — the V0 spec. Read the V0 spec first, then
`QUICK_WRITE_IMPLEMENTATION_TASK.md` and `product/11..20`. Implemented:
see `docs/reports/QUICK_WRITE_V0_1_IMPLEMENTATION_REPORT.md`.

For the local Idea Box, the **V0.7 extension** at
`docs/narrative-writing-product-v0.7-idea-box-spec/` extends V0/V0.1. Read
those base specs first, then `IDEA_BOX_IMPLEMENTATION_TASK.md` and
`product/36..38`. Implemented: see
`docs/reports/PRODUCT_V0_7_IDEA_BOX_IMPLEMENTATION_REPORT.md`.

For article sharing, the **V0.8 extension** at
`docs/narrative-writing-product-v0.8-sharing-spec/` extends the product with
immutable, revocable public snapshots. Read its implementation task and
`product/39..41`. Implemented: see
`docs/reports/PRODUCT_V0_8_SHARING_IMPLEMENTATION_REPORT.md`.

For export/backup work, read the **V0.2 extension** at
`docs/narrative-writing-product-v0.2-export-backup-spec/`. For optional
pre-writing angle confirmation, read V0 and V0.1 first, then the **V0.3
extension** at `docs/narrative-writing-product-v0.3-angle-confirmation-spec/`.
These extensions govern only their named product surfaces and do not reopen
engine scope.

Engine reference (internals only):

1. `docs/00_PROJECT_OVERVIEW.md`
2. `docs/12_THEORY.md`
3. `docs/01_ARCHITECTURE.md`
4. `docs/02_WIR_SPEC.md`
5. `docs/03_AGENT_CONTRACTS.md`
6. `docs/04_PROMPT_SPEC.md`
7. `docs/05_CRITIC_SPEC.md`
8. `docs/06_PATCH_PROTOCOL.md`
9. `docs/09_DATA_AND_RUN_FORMAT.md`
10. `docs/11_ACCEPTANCE_CRITERIA.md`

## Core Rules

- Engine V1/V1.2 scope is closed; do not add roadmap engine features unless
  explicitly requested.
- Product work follows `PRODUCT_IMPLEMENTATION_TASK.md` milestones M0–M10.
- Prefer simple Python and explicit data flow.
- Do not introduce LangGraph, CrewAI, AutoGen, or another heavy orchestration framework.
- Keep prompts externalized in `/prompts`.
- Validate structured outputs with schemas.
- Keep model providers replaceable.
- Persist every intermediate artifact.
- Do not silently change WIR semantics.
- Engine internals stay behind the product's engine adapter; user-facing UI
  must not expose WIR/Critic/Patcher (see Product V0 spec).
- If code and specification conflict, treat the specification as source of truth.
- If the specifications themselves conflict, prefer the more specific and
  normative document (Product V0 spec wins for product-layer questions),
  report the conflict, and record the decision.

## Before Coding

For engine work: produce a short implementation review (understanding,
spec inconsistencies, file structure, milestones, risks), then implement in
the order defined by `docs/10_IMPLEMENTATION_PLAN.md`.

For product work: create `docs/reports/PRODUCT_IMPLEMENTATION_REVIEW.md` as required by
`PRODUCT_IMPLEMENTATION_TASK.md` before writing code.

## Non-Goals

Do not implement:

- Fine-tuning
- LoRA
- RAG
- author-style extraction
- pattern retrieval
- multi-agent graph frameworks
- production authentication
- distributed execution
- autonomous long-running loops
- Product V0 out-of-scope items (see `product/09_V0_SCOPE.md`)

Note: a desktop web UI **is in scope** — governed by the Product V0 spec.

## Design Principle

The system must optimize for:

`meaning progression > reader-state fidelity > natural prose > stylistic decoration`

Do not turn the system into a generic "make this more literary" prompt wrapper.
