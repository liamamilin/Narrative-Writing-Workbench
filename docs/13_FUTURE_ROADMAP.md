# 13 — Future Roadmap

This document describes future directions only.

Do not implement these features in V1.

## V1 — WIR Workflow

Goal:

```text
Input
→ Architect
→ WIR
→ Writer
→ Critic
→ Patch
```

Research questions:

- Does WIR beat direct prompting?
- Does Reader-State WIR beat ordinary outline?
- Does Patch beat rewrite?

---

## V2 — Writing Pattern Library

Create explicit reusable operators such as:

- delayed reveal
- reinterpretation
- escalation
- perspective dive
- semantic echo
- circular landing

Patterns should include:

- purpose
- mechanism
- when to use
- failure modes
- compatible patterns
- examples

---

## V3 — Writing Profile Extraction

Input:

- author corpus
- article corpus
- chapter corpus

Output:

```text
Writing Profile =
Meaning Preferences
+ Reader-State Patterns
+ Narrative Devices
+ Language Realization
```

Avoid reducing style to vocabulary statistics.

---

## V4 — Dynamic Pattern Selection

Architect selects patterns based on:

- task
- intended experience
- source material
- reader-state goal

---

## V5 — Multi-Critic and Benchmark Expansion

Possible critics:

- structural critic
- prose critic
- factual critic
- style critic

Only add complexity if ablation shows value.

---

## V6 — Trajectory Dataset

Accumulate:

```text
Input
→ WIR
→ Draft
→ Critique
→ Final
```

Add human preference labels where possible.

---

## V7 — Distillation / Fine-Tuning

Only after the workflow is validated and enough process data exists.

Possible targets:

- smaller specialized Architect
- specialized Critic
- Writer conditioned on WIR
- end-to-end distilled writing model

The training objective should capture process quality, not merely surface imitation.
