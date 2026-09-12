# QUICK_WRITE_IMPLEMENTATION_TASK

## Objective

Extend Product V0 with Quick Write.

Do not replace the existing source-grounded flow.

Add:

```text
Topic → Meaning Discovery → Angle → WIR → Draft
```

## Read First

Read original Product V0 specs, then this V0.1 package in numerical order.

Before coding create:

```text
../reports/QUICK_WRITE_IMPLEMENTATION_REVIEW.md
```

Include:
- understanding
- integration with V0
- Meaning Discovery schema
- prompt/model strategy
- angle selection strategy
- route/component changes
- persistence/API changes
- tests
- ambiguities

## Hard Product Rules

- no raw chain-of-thought
- no hidden deliberation logs
- no named-person style imitation
- no web research/RAG in this task

## Meaning Discovery Interface

Suggested:

```python
discover_meaning(topic, config) -> MeaningDiscovery
```

Must return:
- topic
- candidate angles
- selected angle
- core question
- deep meaning
- reader end state

Use structured output + schema validation.

Allow at most one repair attempt, consistent with Harness conventions.

## Angle Selection

Default:

```text
Auto Discover
```

Prioritize:

```text
meaning value
structural potential
specificity
non-cliché
```

not rhetorical grandness.

## WIR Integration

Selected meaning must explicitly feed Architect/WIR.

Deep Narrative must not bypass the structure stage.

## Writing Modes

At minimum:

```text
deep_narrative
clear_essay
fiction
free_writing
```

Deep Narrative is flagship.

## Retry Semantics

### Try Another Angle
Rerun Meaning Discovery / selection.

### Rewrite Same Angle
Preserve angle and rerun downstream generation.

These must be separate code paths.

## Persistence

Persist lineage:

```text
task
topic
meaning_discovery
selected_angle
engine_plan
draft/version
```

## Required Tests

1. topic-only task
2. valid Meaning Discovery schema
3. invalid structured-output repair
4. multiple distinct candidates
5. selected angle persisted
6. WIR receives angle/deep meaning
7. another-angle reruns discovery
8. same-angle rewrite preserves angle
9. source-grounded mode unchanged
10. draft-revision mode unchanged
11. factuality warning
12. source transition
13. core meaning lock defaults ON
14. version lineage

## Milestones

Q0 Implementation Review  
Q1 Input mode + persistence  
Q2 Meaning Discovery  
Q3 Angle Selection  
Q4 WIR Integration  
Q5 Quick Write UI  
Q6 Retry Semantics  
Q7 Factuality / Source Transition  
Q8 Tests  
Q9 Acceptance Review

## Completion

Create:

```text
../reports/QUICK_WRITE_V0_1_IMPLEMENTATION_REPORT.md
```

Include:
- files changed
- data/API changes
- Meaning Discovery design
- UI changes
- tests/results
- limitations
- deviations
- example flows

## Stopping Rule

Stop at V0.1 acceptance criteria.

Do not start:
- Research Mode
- Pattern Library
- style marketplace
- V0.2
without explicit instruction.
