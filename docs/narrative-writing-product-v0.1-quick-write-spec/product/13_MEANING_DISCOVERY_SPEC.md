# Meaning Discovery Specification

## Purpose

Quick Write adds the missing first stage:

```text
Topic → Meaning Selection
```

Overall model:

```text
Writing = Meaning Selection + Reader State Control + Language Realization
```

## Suggested Internal Output

```yaml
topic: ""
surface_question: ""
candidate_tensions: []
candidate_angles: []
selected_angle: ""
core_question: ""
deep_meaning: ""
common_reading: ""
new_reading: ""
reader_end_state: ""
constraints: []
```

Do not expose raw reasoning traces.

## Required Questions

- What is the topic?
- What obvious question does it raise?
- What tension makes it worth exploring?
- What would a generic answer say?
- What does this piece add?
- What question can organize the whole piece?
- What should the reader understand by the end?

## Candidate Generation

Generate 3–5 meaningfully different candidate angles.

Bad:

```text
失败让人成长
失败带来成长
失败让人成熟
```

Good:

```text
A. 失败摧毁的不只是目标，而是过去投入的解释框架
B. 失败会制造身份危机
C. 失败重新定价已经支付的成本
D. 失败迫使人承认控制感曾经是幻觉
```

## Candidate Quality

Rank by:
- novelty
- explanatory power
- emotional weight
- expandability
- progression potential
- specificity

Reject fake depth:
- cliché rephrasing
- vague philosophy without mechanism
- unsupported authority
- angle cannot support several distinct beats

## Output to WIR

At minimum:

```text
selected_angle
core_question
deep_meaning
reader_end_state
key_tensions
```

Meaning Discovery does not write prose.
