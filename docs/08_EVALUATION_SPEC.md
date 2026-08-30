# 08 — Evaluation Specification

## 1. Evaluation Layers

V1 supports three evaluation layers:

1. rule-based diagnostics
2. LLM pairwise judge
3. human pairwise review

## 2. Rule-Based Diagnostics

Rule-based checks are not quality judges.

They flag suspicious features such as:

- repeated rhetorical templates
- excessive paragraph uniformity
- extreme sentence length
- repeated abstract terms
- repeated transition phrases
- excessive explicit moral language

Their purpose is diagnostic.

## 3. LLM Judge

LLM evaluation must be anonymous.

Do not reveal which text was produced by which system.

Preferred format:

- Text A
- Text B

Questions:

1. Which has stronger immersion?
2. Which has stronger progression?
3. Which has higher meaning density?
4. Which shows better restraint?
5. Which is more coherent?
6. Which feels more natural?
7. Which is better overall?

Allowed answers:

- A
- B
- Tie

The judge should provide a brief rationale.

## 4. Human Evaluation

Use pairwise comparison rather than 1–10 scoring.

Allowed:

- A better
- B better
- Tie

Reason tags:

- immersion
- progression
- meaning
- naturalness
- restraint
- coherence
- ending
- other

## 5. Primary Metrics

### Overall Win Rate

```text
WinRate(systemA, systemB)
```

### Dimension Win Rates

Track:

- immersion
- progression
- meaning density
- restraint
- coherence
- naturalness

## 6. Writing Gain

Working concept:

```text
Writing Gain =
weighted improvement across target dimensions
```

V1 should report both:

- overall pairwise win rate
- per-dimension win rates

## 7. Interpretation

The intended V1 result is not necessarily "WIR wins every dimension."

A strong result may look like:

- substantial progression gain
- substantial immersion gain
- substantial restraint gain
- similar naturalness

This would support the architectural hypothesis.

## 8. Evaluation Bias

Do not rely exclusively on LLM judges for literary quality.

Model-on-model evaluation can create style preference loops.

Human pairwise review remains the highest-confidence signal for important benchmark decisions.
