# 03 — Agent Contracts

## 1. Purpose

This document defines strict responsibility boundaries.

Agent quality depends partly on preventing role leakage.

---

## 2. Architect Contract

### Input
- source material
- user writing instruction
- task constraints

### Output
- schema-valid WIR

### Responsibilities
- select meaningful core
- identify core experience
- define surface and deep meaning
- define final realization
- design reader-state transitions
- design beat sequence
- control information release
- choose approved devices

### Must Not
- write polished prose
- optimize for verbal beauty
- invent unsupported facts
- add generic morals
- use style imitation as a shortcut

### Primary Optimization Target
`meaning progression`

---

## 3. Writer Contract

### Input
- source material
- user instruction
- WIR

### Output
- prose draft

### Responsibilities
- faithfully render WIR
- preserve facts
- preserve beat order
- preserve reveal timing
- realize perspective
- use natural language
- maintain paragraph-level progression

### Must Not
- redesign WIR
- add new themes
- add new facts
- reveal future information early
- add moral lessons
- insert generic philosophy
- inflate emotional intensity without support

### Priority Order

1. factual fidelity
2. WIR fidelity
3. reader-state fidelity
4. natural prose
5. stylistic quality

---

## 4. Critic Contract

### Input
- source material
- user instruction
- WIR
- draft

### Output
- schema-valid critique

### Responsibilities
- audit WIR fidelity
- identify structural violations
- evaluate prose quality
- identify anti-patterns
- assign severity
- identify passages to preserve
- define patch targets
- produce actionable patch instructions
- decide PASS or PATCH_REQUIRED

### Must Not
- rewrite the prose
- give vague advice
- introduce a new interpretation
- optimize for maximal ornament
- punish intentional restraint

### Required Diagnosis Form

Each actionable issue must contain:

`location → diagnosis → effect → action`

---

## 5. Patcher Contract

### Input
- source material
- user instruction
- WIR
- draft
- critique

### Output
- patched final text

### Responsibilities
- preserve successful material
- modify only necessary passages
- resolve reported failures
- maintain original voice and rhythm where possible

### Must Not
- fully regenerate the text
- introduce new facts
- introduce new themes
- reinterpret the story
- rewrite preserved passages without necessity

### Primary Optimization Target
`minimal successful correction`

---

## 6. Shared Rule

No agent is allowed to silently compensate for another agent's failure by changing the intended semantics.

If a WIR design appears invalid, the correct behavior is to report the issue, not to invent a replacement architecture.
