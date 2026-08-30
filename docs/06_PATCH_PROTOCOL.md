# 06 — Patch Protocol

## 1. Principle

```text
Patch ≠ Rewrite
```

The goal is to fix identified failures while preserving successful text.

## 2. Revision Equation

Conceptually:

```text
Draft2 = Draft1 - Failures + Corrections
```

Not:

```text
Draft2 = GenerateAgain()
```

## 3. Allowed Patch Scope

The Patcher may modify:

- explicit patch targets
- immediately adjacent text required for coherence
- references broken by the patch

The Patcher should not modify unrelated successful passages.

## 4. Preserve Priority

Any passage listed in `preserve` must remain unchanged unless a patch creates an unavoidable contradiction.

If preservation becomes impossible, the Patcher should minimize change.

## 5. Forbidden Additions

The Patcher must not introduce:

- new facts
- new events
- new character motives
- new themes
- new metaphors unrelated to the patch
- new moral conclusions
- new reader-state architecture

## 6. Patch Order

1. fatal/major fidelity problems
2. reveal timing
3. progression
4. over-explanation
5. abstraction problems
6. local prose issues
7. rhythm issues

## 7. One-Pass Rule

V1 allows at most one Patch pass.

There is no Critic → Patcher → Critic recursive loop in V1.

## 8. Patch Quality Principle

A successful patch should make the failure disappear without making the edit itself conspicuous.

Minimality is a feature.
