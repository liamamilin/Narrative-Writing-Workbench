# Input Modes Specification

## Three Entry Modes

### A. Start with an Idea

```text
Topic
→ Meaning Discovery
→ Angle
→ WIR
→ Writer
```

### B. Write from Material

```text
Source + Intent
→ WIR
→ Writer
```

### C. Improve a Draft

```text
Draft + Revision Intent
→ Diagnose
→ Patch
```

## Home Presentation

```text
What do you want to do?

[ Start with an idea ]
Turn a topic into a strong piece of writing

[ Write from material ]
Turn notes and sources into a draft

[ Improve a draft ]
Revise without rewriting everything
```

## Internal Type

```text
input_mode:
  topic_only
  source_grounded
  draft_revision
```

## Behavioral Difference

`topic_only` may interpret, abstract, connect ideas, and choose an angle.

`source_grounded` prioritizes factual fidelity and source constraints.

`draft_revision` prioritizes local preservation and patch safety.

Do not silently switch modes.
