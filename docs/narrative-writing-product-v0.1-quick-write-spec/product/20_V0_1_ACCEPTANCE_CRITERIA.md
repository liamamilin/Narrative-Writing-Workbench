# V0.1 Acceptance Criteria

## Home

User can choose:

```text
Start with an Idea
Write from Material
Improve a Draft
```

## Quick Write

User can:

1. enter a topic
2. optionally choose writing mode
3. leave Angle = Auto Discover
4. set length
5. click Write
6. receive a draft in the existing Workspace

## Meaning Discovery

System must produce internally:

- multiple distinct candidate angles
- one selected angle
- core question
- deep meaning
- reader end state

No raw reasoning trace is required or exposed.

## Angle Quality

Manual acceptance should verify:

- candidates are not trivial paraphrases
- selected angle is not a generic cliché
- selected angle can support multiple progression beats

## WIR Handoff

Selected meaning must be traceable into WIR.

Writer must not independently replace the selected thesis.

## Retry

`Try Another Angle` reruns meaning selection.

`Rewrite Same Angle` preserves selected angle.

## Workspace Integration

Quick Write uses the same:

- Draft editor
- Review
- Locks
- Patch
- Versions
- Writing Map

No duplicate editor.

## Meaning Lock

After generation:

```text
Preserve Core Meaning = ON
```

for ordinary revisions.

## Factuality

- topic-only does not claim source grounding
- fact-heavy topics can trigger warning
- adding sources can transition mode

## Failure Safety

Meaning Discovery failure:
- no broken draft
- retry possible

Writer failure:
- meaning/angle remains available
- retry possible

## Required Tests

At minimum:

- topic-only task creation
- Meaning Discovery schema validation
- multiple candidate angles
- selected angle persisted
- WIR receives selected meaning
- Writer receives WIR
- another-angle path
- same-angle regeneration
- factuality flag
- source transition
- version lineage
- core meaning lock default
- original source-grounded flow unchanged

## Definition of Done

```text
Topic
→ Meaning Discovery
→ Angle
→ WIR
→ Draft
→ Workspace
```

works reliably without Source.
