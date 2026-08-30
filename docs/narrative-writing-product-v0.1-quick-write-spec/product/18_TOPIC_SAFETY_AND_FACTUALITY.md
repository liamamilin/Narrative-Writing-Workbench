# Topic Safety and Factuality

## Core Distinction

Topic-only writing is not source-grounded writing.

The product must preserve this distinction.

## Conceptual / Creative Topics

Suitable without sources:

- abstract concepts
- narrative mechanisms
- reflection prompts
- fictional premises
- interpretation
- emotional themes

Examples:

```text
什么是野心？
为什么知道结局仍然会紧张？
为什么人会对失去的东西重新赋予意义？
```

## Fact-Heavy Topics

Examples:

```text
罗马帝国为什么灭亡？
2026 年中国人口发生了什么？
某家公司为什么裁员？
```

These may require externally verifiable facts.

V0.1 should not pretend general model knowledge is source-grounded.

## Recommended UX

If a fact-heavy topic is detected:

```text
This topic may depend on factual claims.

Continue using general knowledge, or add sources for tighter grounding.
```

Actions:

```text
Continue
Add Sources
```

## Source Transition

If the user adds sources:

```text
topic_only → source_grounded
```

Persist this transition.

## Future Research Mode

Future only:

```text
Topic
→ Research
→ Sources
→ Meaning Discovery
→ WIR
→ Draft
```

Research output must become explicit Source.

## No Fake Authority

Without supporting sources, avoid statements such as:

```text
研究已经证明……
数据显示……
历史学家普遍认为……
```

unless genuinely grounded.
