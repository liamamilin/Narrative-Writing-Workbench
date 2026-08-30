# 02 — WIR Specification

## 1. Definition

**WIR** = Writing Intermediate Representation.

WIR is a structured representation of:

- what the text should mean
- what the reader should experience
- how reader state should change
- when information should be revealed
- which narrative devices should be used
- which constraints must be preserved

WIR is not prose and not a conventional outline.

## 2. Core Principle

Every beat must produce at least one of:

- knowledge gain
- belief change
- expectation change
- emotional change
- question creation or resolution
- meaning gain

If a beat produces none of these, it is redundant.

## 3. Top-Level Structure

```yaml
wir_version: "0.1"

task:
  type: ""
  objective: ""

meaning:
  core_experience:
    description: ""
    emotion: ""
    intensity: 1
  surface_meaning: ""
  deep_meaning: ""
  final_realization: ""

reader_state:
  initial:
    knowledge: []
    belief: []
    expectation: []
    emotion: []
    questions: []
  target:
    knowledge: []
    belief: []
    expectation: []
    emotion: []
    questions: []

perspective:
  focalizer: ""
  distance: "close|medium|distant"
  allowed_shifts: []

beats: []

devices: []

constraints: {}
```

## 4. Meaning

### core_experience
The primary experience the text should create.

Example:

> A delayed understanding that arrives too late to repair the relationship.

### surface_meaning
What the material appears to be about at first level.

### deep_meaning
The deeper structure worth expressing.

### final_realization
The final reinterpretation or understanding the reader should reach.

Do not confuse `deep_meaning` with a generic moral.

Bad:

> Life is complicated.

Good:

> The father's attempt to protect the child reproduces the very injury he fears.

## 5. Reader State

Reader state is modeled as:

```text
R = Knowledge + Belief + Expectation + Emotion + Questions
```

The model is intentionally lightweight in V1.

### Knowledge
What the reader knows as fact.

### Belief
How the reader currently interprets those facts.

### Expectation
What the reader predicts or anticipates.

### Emotion
The intended emotional state or tendency.

### Questions
Open narrative or interpretive questions.

## 6. Beat Schema

```yaml
id: "B1"

function:
  primary: "entry"
  secondary: "curiosity"

reader_transition:
  from: ""
  to: ""

information:
  reveal: []
  conceal: []

meaning_gain: ""

emotional_effect:
  target: ""
  intensity: 1

perspective:
  focalizer: ""
  distance: "close"

devices: []

exit_questions: []
```

## 7. Allowed Beat Functions

V1 enum:

- `entry`
- `context`
- `immersion`
- `escalation`
- `complication`
- `reveal`
- `reinterpretation`
- `perspective_shift`
- `contrast`
- `payoff`
- `landing`

Do not invent additional beat types in V1.

## 8. Allowed Devices

V1 enum:

- `delayed_explanation`
- `partial_reveal`
- `reinterpretation`
- `perspective_dive`
- `perspective_shift`
- `contrast`
- `semantic_echo`
- `escalation`
- `specific_to_abstract`
- `abstract_to_specific`
- `controlled_omission`
- `circular_landing`

## 9. Devices Are Operators, Not Adjectives

Bad device:

> literary

Bad device:

> profound

Valid device:

> delayed_explanation

A valid device describes an operation on information, perspective, meaning, or expectation.

## 10. Constraints

Suggested V1 constraints:

```yaml
constraints:
  factual_fidelity: true
  allow_new_facts: false
  max_explicit_moralization: 0
  avoid_generic_philosophy: true
  avoid_emotional_labeling_when_behavior_suffices: true
  max_contrast_redefinition_patterns: 1
  target_length: null
```

## 11. Architect Validation Questions

Before returning WIR:

1. Does every beat change reader state?
2. Does every beat have meaning gain?
3. Are any two beats redundant?
4. Is final realization revealed too early?
5. Is emotion earned by preceding information?
6. Are there unsupported thematic claims?
7. Is the information release order intentional?
8. Does perspective remain coherent?

## 12. WIR Invariant

The Writer may realize WIR differently at the sentence level, but must not:

- reorder major beats without authorization
- reveal concealed information early
- change deep meaning
- invent a new final realization
- replace the intended reader-state trajectory
