# 05 — Critic Specification

## 1. Purpose

The Critic is a diagnostic system, not a generic reviewer.

It evaluates:

1. WIR fidelity
2. prose quality
3. anti-patterns
4. revision necessity

---

## 2. Writing Quality Score

V1 score:

```text
WQ = M + P + I + S + R + C
```

Each dimension is scored 1–5.

### M — Meaning Density
Does each paragraph contribute actual meaning?

### P — Progression
Does reader understanding or experience move forward?

### I — Immersion
Does the prose keep the reader inside the narrative/analysis rather than repeatedly stepping outside to explain?

### S — Specificity
Does the prose rely on concrete evidence, behavior, images, or precise relations rather than vague abstraction?

### R — Restraint
Does the text avoid over-explaining, over-emoting, and over-moralizing?

### C — Coherence
Do logic, perspective, causality, and meaning remain continuous?

Maximum: 30.

---

## 3. Anti-Pattern Taxonomy

V1 anti-patterns:

- `fake_depth`
- `abstract_padding`
- `generic_philosophy`
- `over_explanation`
- `repetitive_contrast`
- `emotional_overstatement`
- `early_reveal`
- `rhythm_monotony`

### fake_depth
A sentence appears profound but adds little or no recoverable meaning.

Diagnostic question:

> If this sentence is deleted, does the text lose specific meaning?

### abstract_padding
Abstract commentary expands length without changing reader state.

### generic_philosophy
Universal claims not earned by the material.

### over_explanation
The prose explicitly explains what concrete actions or prior context already imply.

### repetitive_contrast
Repeated dependence on structures such as "not A but B."

### emotional_overstatement
The prose declares stronger emotion than the narrative has earned.

### early_reveal
Critical information appears before its WIR-assigned beat.

### rhythm_monotony
Persistent repeated sentence/paragraph rhythm.

---

## 4. Severity

Allowed values:

- `minor`
- `moderate`
- `major`
- `fatal`

### Minor
Local roughness with little structural effect.

### Moderate
Noticeable prose or progression issue worth patching.

### Major
Damages a planned reveal, reader-state transition, perspective, or central meaning.

### Fatal
Breaks factual fidelity or reverses the intended interpretation.

---

## 5. Required Issue Structure

```yaml
location: "P4-S2"
severity: "moderate"
diagnosis:
  type: "over_explanation"
  description: ""
effect: ""
action: ""
```

---

## 6. Preserve List

The Critic must identify successful passages.

Example:

```yaml
preserve:
  - "P1"
  - "P3-S3"
```

The purpose is to prevent global regeneration.

---

## 7. Decision Rule

Suggested V1 default:

PASS if:

- fatal = 0
- major = 0
- moderate <= 2
- WQ >= 24

Otherwise:

`PATCH_REQUIRED`

This threshold should remain configurable.

---

## 8. Critic Output Skeleton

```yaml
decision: "PASS|PATCH_REQUIRED"

fidelity:
  score: 1-5
  violations: []

quality:
  meaning_density: 1-5
  progression: 1-5
  immersion: 1-5
  specificity: 1-5
  restraint: 1-5
  coherence: 1-5

anti_patterns: []

issues: []

preserve: []

patch_targets: []

revision_strategy: []
```
