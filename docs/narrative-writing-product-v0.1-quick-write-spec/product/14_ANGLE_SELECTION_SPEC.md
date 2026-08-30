# Angle Selection Specification

## User-Facing Control

Default:

```text
Angle: Auto Discover
```

Advanced options may include:

```text
Auto Discover
Psychological
Narrative
Philosophical
Social
Personal
Structural
```

These are preferences, not rigid ontologies.

## Auto Discover

Auto Discover means:

```text
find the most meaningful and structurally generative framing
```

not random variation.

## Suggested Angle Object

```yaml
angle:
  id: A1
  label: ""
  thesis_hint: ""
  mechanism: ""
  reader_shift: ""
  risks: []
```

## Strong Angle Criteria

A strong angle:
- narrows the topic
- creates a real question
- permits progression
- supports multiple beats
- changes how the reader sees the topic
- does not depend on empty rhetoric

## Example

Topic:

```text
为什么人会怀念已经结束的关系？
```

Weak:

```text
因为人都有感情。
```

Better:

```text
人怀念的未必是关系本身，而是那段关系曾经替自己证明过的某种身份。
```

Possible progression:

```text
失去对象
→ 失去共同生活
→ 失去被某种方式看见的自己
→ 怀念变成身份追索
```

## User Override

If the user provides an explicit angle:

```text
Explicit User Angle > Auto Discover
```

Meaning Discovery should refine it, not overwrite it.

## V0.1 Boundary

Optional:

```text
Try another angle
```

Do not implement a complex angle graph/editor in V0.1.
