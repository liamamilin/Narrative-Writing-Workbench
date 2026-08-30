# Quick Write Vision

## Problem

The current product assumes `Task + Source`, but many writing tasks begin with only a topic:

- 谈谈失败
- 为什么人会怀念已经结束的关系？
- 为什么越想摆脱父亲，反而越像父亲？
- 为什么知道结局的故事仍然有悬念？

Ordinary LLMs often expand these into generic summaries.

Quick Write instead runs:

```text
Topic
→ Find something worth saying
→ Decide how the reader discovers it
→ Write
```

## Product Promise

> Start with one idea. Get a piece with a real angle, progression, and weight.

## Core Pipeline

```text
Topic
↓
Meaning Discovery
↓
Angle Selection
↓
Reader Journey / WIR
↓
Writer
↓
Draft
```

## Relationship to Existing Product

```text
Topic → Meaning → Structure → Draft
Source + Intent → Structure → Draft
Existing Draft → Diagnose → Patch
```

## Deep Narrative

User-facing flagship mode:

```text
Deep Narrative
```

Mechanisms:
- experience before abstraction
- delayed explanation
- gradual reinterpretation
- semantic progression
- controlled omission
- restrained landing

Do not label this as imitation of a named living creator's style. Productize general mechanisms, not a person's distinctive voice.
