# 18 Beat Budget Spec

Status: implemented (optional, backward compatible). Motivated by V1.1:
WIR-driven drafts tended to over-expand text. This is a lightweight budget
mechanism, NOT a WIR redesign.

## 1. Principle

**Meaning Gain / Word Cost.** Not every reader-state transition deserves a
full paragraph. Prose should be spent where meaning turns; transitions that
only move the reader a little get few words or merge into neighbors.

## 2. Schema (optional fields)

`schemas/wir.schema.json`:

- `task.target_length`: `integer | null` — mirrors the constraint when the
  caller provides one.
- each beat: `prose_budget`: `"core" | "support" | "bridge"` (optional).

Preferred interpretation:

| value | meaning |
|-------|---------|
| core | carries the meaning turn; may receive substantial prose |
| support | brief development |
| bridge | minimal prose; MAY be merged into an adjacent paragraph |

Old WIRs without these fields stay valid (fields are optional; no required
list changed; `additionalProperties` untouched except for the new keys).
The outline baseline already had the equivalent mechanism (`emphasis:
full/brief/omit`), so A1 and A2 face the same length policy — a fairness
requirement for H2-clean.

## 3. Prompt wiring

- `prompts/architect.md`: assigns `prose_budget` per beat when the piece has
  transitions of unequal weight; mirrors `target_length` into
  `task.target_length`; keeps beat count compatible with the budget.
- `prompts/outline_architect.md`: uses `emphasis` with the same
  Meaning-Gain/Word-Cost principle.
- All three writer prompts: a Length Budget section — respect the target
  length from the user message; core/support/bridge spending rules; bridge
  units may be merged.
- Writer user messages gain an `## Output Budget` block whenever
  `target_length` is set:

```
Target length: about {N} characters in total. Not every structural unit
deserves a full paragraph: weigh Meaning Gain against Word Cost. Units marked
core may receive substantial prose; support units get brief development;
bridge units get minimal prose and may be merged into an adjacent paragraph.
```

## 4. Non-goals

- No word-count enforcement code, no per-beat quotas, no WIR semantic change.
- The budget is advisory to the model; over/under-shoot is still measured by
  the deterministic `task_completion` gate and `mean_chars` in reports.

## 5. Evaluation hook

V1.2 run reports compare average output length per variant (A1 vs A2, W0 vs
WGI) against `target_length` to check whether the budget reduced
over-expansion without flattening progression (progression is judged blindly;
length is reported as a covariate, never as a quality score).
