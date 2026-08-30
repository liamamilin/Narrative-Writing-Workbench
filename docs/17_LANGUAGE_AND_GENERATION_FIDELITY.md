# 17 Language and Generation Fidelity

Status: implemented. Language mismatch is a **functional generation
failure**, not a prose-quality problem. This document defines the expected
language contract and the Writer-boundary repair policy (V1.2).

## 1. Expected language contract

`expected_language: zh | en | auto` is resolved per run with priority:

1. `case["expected_language"]` (explicit task contract; the 10 smoke cases
   are all `zh`),
2. `config.expected_language` (YAML, default `auto`),
3. deterministic zh/en text heuristic over instruction+material (`auto`).

Implemented in `app/gates.py:resolve_expected_language`; the
`expected_language_match` hard gate now evaluates against the resolved
explicit value, not only the heuristic.

## 2. Writer prompt boundary

Every Writer user message carries an explicit directive block:

```
## Output Language

OUTPUT LANGUAGE: Chinese

Write the complete final prose in Chinese. Do not switch to English even if
internal representations, examples, schemas, or model reasoning contain
English. Never mix languages in the prose.
```

(English target uses the mirrored wording.) Applied to all three writer
prompts — `writer.md`, `writer_gi.md`, `writer_outline.md` — as system-level
rules plus the dynamic user-message block.

Scope guard: this is a functional-fidelity instruction. The Architect/WIR
semantics were NOT modified to solve language leakage; no writing-policy
content changed in any writer prompt (W0 keeps its original policy; the
language and budget sections are fidelity addenda).

## 3. Repair policy (app/language.py)

After every Writer generation, `expected_language_match` runs immediately:

- **Match** → final sample; `language_attempts = 1`, `language_repaired = False`.
- **Mismatch** → do NOT send the text to the Critic; do NOT count it as the
  final Writer sample; perform **exactly one** repair/regeneration attempt
  using the SAME material, instruction, structure and Writer policy, with an
  explicit Language Repair directive demanding the expected language and
  requiring the same meaning, structure and order to be preserved.
  - Repair matches → `language_attempts = 2`, `language_repaired = True`.
  - Repair still fails → `functional_failure = true`
    (`language_functional_failure`); the row is marked failed and excluded
    from Critic branching; its pair is not packaged.

The first failed generation is preserved (`original_text` in the row and
artifact) — never silently discarded.

## 4. Persisted fields

Every V1.2 output row and artifact carries:

```
language_attempts        int    (1 or 2)
language_repaired        bool   (repair succeeded on attempt 2)
language_functional_failure bool
original_language        str    (detect_language of attempt 1)
final_language           str    (detect_language of the final text)
original_text            str    (only when attempt 1 mismatched)
```

`summary.json → v12.per_variant` reports repair counts per variant and the
total attempted generations, so leakage is visible before review.

## 5. Relation to hard gates

The repair policy reduces gate failures BEFORE review; the
`expected_language_match` gate remains as the final deterministic check and
still flips gated aggregation views if a functional failure survives. Raw
blind judgments are never mutated by either mechanism.
