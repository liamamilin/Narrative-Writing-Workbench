# Quick Write Flow Specification

## Golden Path

```text
Home
↓
Start with an Idea
↓
Enter Topic
↓
Write
↓
Meaning Discovery
↓
Angle Selection
↓
WIR
↓
Writer
↓
Draft
↓
Workspace
```

## User Experience

Surface:

```text
Topic → Draft
```

Advanced controls remain optional.

## Retry Semantics

### Try another angle

Rerun:

```text
Meaning Discovery / Angle Selection
```

### Rewrite with same angle

Reuse:

```text
selected angle + meaning
```

and rerun downstream structure/prose only as configured.

These are distinct actions.

## Preserve Meaning

After the user accepts a generated angle:

```text
Preserve Core Meaning = ON
```

by default for normal revisions.

## Fact-Heavy Topic

Example:

```text
为什么罗马帝国灭亡？
```

Possible message:

```text
This topic may depend on factual claims.

[ Continue with general knowledge ]
[ Add sources ]
```

Research-first mode is future scope unless already implemented.
