# QUICK_WRITE_V0_1_IMPLEMENTATION_REPORT

Date: 2026-08-30
Spec: `docs/narrative-writing-product-v0.1-quick-write-spec/`
Review: `QUICK_WRITE_IMPLEMENTATION_REVIEW.md` (Q0)
Status: **V0.1 acceptance criteria met; stopped at V0.1** (no Research Mode,
Pattern Library, style marketplace, or V0.2 work started).

## 1. Summary

Quick Write adds the topic-only entry without replacing the V0 flows:

```text
Topic → Meaning Discovery → Angle → WIR → Writer → Draft → (same) Workspace
```

All three input modes coexist: `topic_only` (new), `source_grounded`,
`draft_revision`. Existing V0 behavior is unchanged (proven by the 135
pre-existing tests staying green). Full suite: **154 passed**.

## 2. Files changed

New:
- `QUICK_WRITE_IMPLEMENTATION_REVIEW.md` — Q0 design review
- `workbench/schemas/meaning_discovery.schema.json` — discovery output schema
- `workbench/meaning_schema.py` — schema + semantic validation, WIR handoff
  block, product-safe summary
- `prompts/meaning_discovery.md` — externalized discovery prompt
- `tests/test_quick_write.py` — 19 tests covering the 14 required
- `QUICK_WRITE_V0_1_IMPLEMENTATION_REPORT.md` — this file

Modified (all additive / mode-guarded):
- `workbench/db.py` — `tasks.input_mode/topic/writing_mode/angle_mode/custom_angle`,
  `engine_plans.meaning_id`, new `meaning_discoveries` table, idempotent
  `_migrate()` for existing databases
- `workbench/engine/__init__.py` — `DiscoveryFailed`; protocol
  `discover_meaning()` + `generate(..., meaning=None)`
- `workbench/engine/mock.py` — deterministic discovery (3 candidates,
  avoid-list, custom→A0); generate records meaning into plan
- `workbench/engine/real.py` — `discover_meaning` via `structured_call`
  (≤1 repair, architect role cfg); `generate` composes the selected meaning
  into the WIR instruction block and tags the plan
- `workbench/service.py` — mode-aware `create_task`, `discover`,
  `_generate_with`, `rediscover_angle`, `regenerate`, `meaning_summary`,
  fact-heavy heuristic, source-transition, core-meaning default, lineage
  ordering (rowid tiebreak)
- `workbench/api.py` — `GET /tasks/:id/meaning`,
  `POST /tasks/:id/rediscover-angle`, `POST /tasks/:id/regenerate`
- `workbench/static/{app.js,styles.css,index.html}` — Home three entries,
  `#/quickwrite` screen, `#/revise`, Workspace meaning card + retry buttons,
  Quick Write progress stages; cache bumped `app.js?v=5`, `styles.css?v=3`

## 3. Data / API changes

- Task fields: `input_mode`, `topic`, `writing_mode`, `angle_mode`,
  `custom_angle` (all defaulted; old rows read as `source_grounded`).
- `meaning_discoveries(id, task_id, topic, selected_angle_id, status,
  data_json, created_at)` — append-only lineage.
- `engine_plans.meaning_id` — links each plan to the discovery that produced it.
- Mode transition recorded in `writing_configs.constraints_json.mode_transitions`.
- New endpoints return V0 error shapes; `GET /meaning` returns exactly
  `{topic, selected_angle, core_question, reader_end_state}`.

## 4. Meaning Discovery design

- Structured JSON validated against `meaning_discovery.schema.json` plus two
  semantic rules in `meaning_schema.validate_meaning`: selected id must be a
  real candidate; candidate labels must not be paraphrase-duplicates.
- One repair attempt on invalid output (reuses `app/structured.structured_call`),
  consistent with Harness convention; second failure → retryable
  `DISCOVERY_FAILED`, no draft touched.
- Engine (`app/`) untouched — V1.2 scope closed. Discovery is orchestrated in
  the workbench adapter; the selected meaning is fed to the existing Architect
  through a composed instruction block (`_compose_topic_instruction`) carrying
  selected_angle / core_question / deep_meaning / reader_end_state /
  key_tensions. Writer receives the WIR unchanged and is told not to replace
  the thesis.
- `fact_heavy` + service heuristic `detect_fact_heavy()` drive the warning;
  topic_only never claims source grounding and the prompt forbids fake authority.

## 5. UI changes

- **Home**: "Start with an idea" / "Write from material" / "Improve a draft".
- **Quick Write** (`#/quickwrite`): topic + example chips, Writing Mode
  (Deep Narrative default), Angle = Auto Discover (advanced custom), length,
  language, **Write** CTA → creates task and auto-runs generation in the
  existing Workspace.
- **Fact-heavy** topics: a `confirm()` gate — continue with general knowledge
  or stay to add sources.
- **Workspace** (topic_only only): a "What this piece is about" card (4 safe
  fields) and two distinct actions — **Try another angle** (rediscover) and
  **Rewrite this angle** (preserve). Progress banner gained Quick Write stages
  ("Finding something worth saying"). No second editor.

## 6. Tests / results

`tests/test_quick_write.py` (19) map to the 14 required:

| # | Required | Test |
|---|---|---|
| 1 | topic-only task | `test_topic_only_task_creation_and_defaults` |
| 2 | valid schema | `test_meaning_discovery_schema_valid` |
| 3 | invalid → repair | `test_structured_repair_path_with_meaning_validator`, `test_invalid_discovery_rejected_and_retryable` |
| 4 | distinct candidates | `test_candidates_must_be_distinct` |
| 5 | selected angle persisted | `test_selected_angle_persisted_with_lineage` |
| 6 | WIR receives meaning | `test_wir_receives_selected_meaning`, `test_topic_instruction_block_contains_meaning` |
| 7 | another-angle reruns discovery | `test_try_another_angle_reruns_discovery_with_avoid_list` |
| 8 | same-angle preserves | `test_rewrite_same_angle_preserves_angle` |
| 9 | source-grounded unchanged | `test_source_grounded_flow_unchanged` |
| 10 | draft-revision unchanged | `test_draft_revision_flow_unchanged` |
| 11 | factuality warning | `test_factuality_detection`, `test_factuality_warning_surface_and_continue` |
| 12 | source transition | `test_adding_sources_transitions_mode_and_persists` |
| 13 | core-meaning lock default ON | `test_preserve_core_meaning_defaults_on` |
| 14 | version lineage | `test_full_lineage_topic_to_version` |

Plus `test_meaning_endpoint_product_safe` (no reasoning trace / candidate
leak). Whole repo: **154 passed** (0 regressions).

**Real-engine end-to-end** (deepseek-v4-flash, topic "为什么越想摆脱父亲，反而越像父亲？"):
- generate → angle "反叛即镜像:用父亲的语法说'我不是你'", 556-char draft (~197s)
- rediscover-angle → genuinely different angle "父亲是自我定义的坐标…", new
  generation (~243s)
- regenerate preserve_angle → same angle, no new discovery, new version (~112s)
- DB lineage verified: 3 plans → 2 discoveries, same-angle reuse confirmed,
  versions `[generation, generation, generation]`, `factuality_warning=False`.

## 7. Limitations

- Fact-heavy detection is a deliberately conservative regex + model `fact_heavy`
  flag; it can miss fact-heavy phrasings (warning only, never blocks Continue).
- Candidate distinctness is enforced only against exact normalized
  paraphrase-duplicates; semantic near-duplicates rely on the model + manual
  acceptance (product/20), not an automated cliché classifier.
- Real Quick Write is ~2 LLM calls (discovery + write), so a topic-only draft
  is slower than a mock one; the progress banner covers the wait.
- Writing modes map onto existing engine task types (no new engine types,
  per closed scope).

## 8. Deviations (recorded)

- Meaning Discovery schema/validator live in `workbench/` rather than the
  engine `SchemaSet`, because engine V1.2 scope is closed; the engine package
  is not modified.
- Discovery reuses the `architect` RoleConfig (no new engine role added).
- Meaning→WIR handoff is done by composing the Architect instruction text in
  the adapter, not by a native engine `meaning` parameter.
- "Improve a draft" uses the existing patch flow (material = your draft); the
  dedicated `#/revise` entry pre-labels the form rather than adding a new
  pipeline.
- Fact-heavy gate uses a native `confirm()` dialog (consistent with the rest
  of the no-build vanilla SPA) instead of a bespoke modal.

## 9. Example flows

```text
Home → Start with an idea → 谈谈失败 → Deep Narrative, Angle=Auto, 900 → Write
  → (discovery) 3–5 angles, one selected → WIR → Writer → Workspace draft
  → [Try another angle] reruns discovery (avoids old) → new draft
  → [Rewrite this angle] keeps meaning, reruns structure/prose → new draft
  → Review / select passage / Patch / Accept / Versions (unchanged V0)

Home → Start with an idea → 为什么罗马帝国灭亡？ → Write
  → fact-heavy gate: Continue (general knowledge, no fake citations) or add
    sources → adding a source flips topic_only → source_grounded (persisted)
```

## 10. Acceptance vs product/20

- Home three entries ✓ · Quick Write 6 steps → draft in existing Workspace ✓
- Discovery produces multiple distinct candidates + one selected + core
  question + deep meaning + reader end state ✓ (no reasoning trace)
- WIR handoff traceable (plan.meaning_id) ✓ · Writer doesn't replace thesis ✓
- Retry: another vs same angle are distinct paths ✓
- Workspace integration: same editor/review/locks/patch/versions/map ✓
- Preserve Core Meaning defaults ON ✓
- Factuality: topic_only doesn't claim grounding; warning; source transition ✓
- Failure safety: discovery/writer failure leaves no broken draft, retry ✓
- Original source-grounded flow unchanged ✓

## Post-delivery hardening (2026-08-31)

Two user-facing bug rounds after Q0-Q9 sign-off; details in
`QUICK_WRITE_IMPLEMENTATION_REVIEW.md` addenda (2026-08-30 / 2026-08-31).

Round A (reported bugs): in-task edits to intent/immersion/explicitness/
target length now reach the engine end-to-end (frontend body →
`_apply_param_overrides` persistence → `_dial_block` prompt injection);
token streaming fixed (SSE start race, seq dedupe, typewriter pacing).

Round B (audit sweep, 16 items): language gate resolves from the discovery
text for topic-led pieces (English topic + Chinese prose no longer fails
the "safety check"); gate failures log reasons and surface human-readable
zh messages; `allow_new_facts` opt-in in `app/gates.py` (default off,
bit-identical for source-grounded runs); non-EngineError no longer strands
tasks in 'generating'; regenerate/rediscover share the concurrency guard;
autosave flush + deduped checkpoint before destructive regenerate; diff
tails; unified target_length validation; settings rollback on failed
hot-swap; pending-patch restore; navigation guards.

Suite: **194 passed** (16 new regression tests). Verified end-to-end on the
real provider (English topic, auto language, 97 delta events, status ready).
