# 04 — Prompt Specification

## 1. Purpose

Prompt files define role behavior.  
They should be explicit, concise, and stable enough for benchmark comparison.

Prompts belong in `/prompts`.

---

## 2. Architect Prompt Requirements

The Architect prompt must state:

> You are a narrative architect. You do not write prose.

Primary objective:

> Design how the reader's understanding, expectation, questions, and emotion should change over time.

Required priorities:

1. meaning selection
2. reader-state transition
3. information release
4. beat progression
5. approved device selection

Required principle:

> Do not optimize for beauty. Optimize for meaning progression.

The Architect must output structured WIR only.

---

## 3. Writer Prompt Requirements

The Writer prompt must explicitly preserve the hierarchy:

1. factual fidelity
2. WIR fidelity
3. reader-state fidelity
4. natural prose
5. style

Required rules:

- concrete before abstract where appropriate
- every paragraph must move something
- do not explain what the reader already understands
- abstraction must be earned
- avoid repeated rhetorical scaffolds
- prefer implication when behavior already carries meaning
- do not force a moral
- landing is a meaning change, not a slogan

---

## 4. Anti-AI Prose Guidance

The Writer should avoid habitual overuse of patterns such as:

- 不是……而是……
- 真正……从来不是……
- 直到这一刻……
- 他终于明白……
- 或许……
- 某种意义上……
- 人性……
- 命运……

These are not banned.  
They are allowed only when structurally justified.

The prompt should target repetitive dependence, not individual phrases.

---

## 5. Critic Prompt Requirements

The Critic must evaluate in two passes:

### Pass A — WIR Fidelity
Check:

- beat order
- reveal timing
- reader-state trajectory
- perspective
- final realization
- factual fidelity

### Pass B — Prose Quality
Check:

- meaning density
- progression
- immersion
- specificity
- restraint
- coherence
- rhythm
- anti-patterns

Critic comments must be local and actionable.

Bad:

> The prose could be more emotionally powerful.

Good:

> P4-S2 explicitly names the character's shame immediately after the action already implies it. Delete or compress the sentence to preserve reader inference.

---

## 6. Patcher Prompt Requirements

The prompt must repeatedly reinforce:

> Patch, do not rewrite.

Required behavior:

- honor preserve list
- edit patch targets first
- modify surrounding text only when required for continuity
- do not introduce new thematic claims
- do not improve unrelated passages merely because they can be improved

---

## 7. Structured Outputs

Architect and Critic prompts should use schema-constrained output whenever provider support exists.

Fallback:

- strict JSON-only instruction
- validation
- one repair attempt
