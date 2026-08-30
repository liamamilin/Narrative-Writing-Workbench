# PRODUCT_V0_IMPLEMENTATION_REPORT

Date: 2026-08-30. Spec: `docs/narrative-writing-product-v0-spec/`
(M0–M10 complete; acceptance = product/10).

## 1. Stack

FastAPI + uvicorn + stdlib sqlite3 + vanilla-JS SPA (no build step).
Chosen per the spec's "equivalent simple stack" clause; documented in
`PRODUCT_IMPLEMENTATION_REVIEW.md` §2. Deps: `requirements-workbench.txt`.

Run: `python3 -m workbench.server` → http://127.0.0.1:8600
Engine mode: `WORKBENCH_ENGINE=mock|real` (mock default; real uses
`WORKBENCH_CONFIG` or `config.live.yaml`), `WORKBENCH_DB` for the DB path.

## 2. Routes (backend, product/07 contract)

```
POST   /projects            GET /projects       GET /projects/:id
POST   /projects/:id/sources
POST   /tasks               GET /tasks          GET /tasks/:id
PATCH  /tasks/:id                    (instruction/title/config/locks — extension)
POST   /tasks/:id/generate   POST /tasks/:id/review   POST /tasks/:id/patch
POST   /tasks/:id/sources    POST /tasks/:id/checkpoint
POST   /patches/:id/accept   POST /patches/:id/reject
GET    /tasks/:id/writing-map
GET    /drafts/:id/versions  PATCH /drafts/:id  (autosave)
GET    /versions/:id         POST /versions/:id/restore
GET    /settings             GET /  (SPA shell)
```

Error shape exactly per spec: `{"error":{"code","message","retryable"}}`.

## 3. Screens / components (frontend, hash router)

| screen | route | implemented |
|---|---|---|
| Home | `#/` | "What are you writing today?", Start Writing, Recent Tasks/Projects |
| New Task | `#/tasks/new` | 6 task types, intent, material, .txt/.md upload, project picker, reader experience (immersion/explicitness/intensity/target length/language), 4 constraints |
| Workspace | `#/tasks/:id` | 3 columns Sources·Draft·Writing Panel; contenteditable paragraphs, click/shift-click passage selection, selection toolbar (Revise/Shorter/Less Explicit/More Natural/More Immersive), presets+custom instruction, Before/After patch cards with Accept/Reject/Try Again, autosave (debounced, Saving…/Saved), Draft↔Writing Map switch, Versions link |
| Writing Map | panel in workspace | read-only beat cards (function, reader_before→after, meaning_gain, ¶ range); click → highlight paragraph |
| Versions | `#/tasks/:id/versions` | history with origin labels (Initial Generation / AI Patch / Manual Checkpoint / Restore), two-version line diff, Restore |
| Project | `#/projects/:id` | tasks, sources, add source, new task |
| Settings | `#/settings` | engine mode display |

Product copy follows `product/08` (no "magic/masterpiece" language; loading
stages "Preparing the draft… / Understanding your material / Designing
progression / Writing the draft").

## 4. Data model

All 9 spec objects as SQLite tables (`workbench/db.py`): projects, sources,
tasks, task_sources, writing_configs, engine_plans, drafts, versions,
proposed_patches, reviews. Invariants enforced in `workbench/service.py`:
one active draft per task; current_version belongs to draft; rejected patch
touches nothing; restore is a new reversible version; locks persisted and
recorded per patch; engine plans traceable to task.

## 5. Engine adapter

`workbench/engine/` — `WritingEngine` protocol
(generate/review/patch/writing_map); `MockWritingEngine` and
`RealWritingEngine` share the interface.

Real adapter maps to the V1.2 engine: Architect→WIR→Writer with
`expected_language` + `write_with_language_repair` + `hard_gates`
(generation), CriticAgent with quality→Strong/Good/Needs-attention
translation and beat→paragraph issue positioning (review), new
`prompts/product_patch.md` selection-scoped lock-aware patcher returning
JSON `{after_text}` or `{lock_conflict}` (patch), WIR beats→paragraph
mapping (writing map). Engine internals never cross the adapter boundary.

## 6. Tests / results

- `tests/test_product_api.py` + `tests/test_product_safety.py`: **29 passed**
  covering every spec-required test: CRUD+validation, generate success,
  generation-failure safety (incl. failure after an existing draft),
  autosave (no versioning), patch propose/accept/reject/try-again,
  stale-base & double-accept guards, version create/restore/reversible,
  lock persistence, lock-conflict fail-safe, writing-map serialization
  product-safe, review positioning, language-safe rejection, and a
  static-UI scan asserting no WIR/Critic/Patcher/Architect/beat terms in
  shipped HTML/JS/CSS.
- Full repo suite: **135 passed** (106 engine + 29 product).
- Live real-engine smoke (deepseek-v4-flash): generate 655 zh chars →
  review all-strong → patch proposed → accept → versions
  `[generation, patch]` → writing map clean. Log: `.scratch/wb_real_smoke.log`.

## 7. Acceptance checklist (product/10)

Golden path ✓ · Workspace 3-pane with dominant draft ✓ · Generation
mock/real isolated, failure-safe, language-safe, no agent logs ✓ · Review
Show/Fix ✓ (labels, no fake 8.7/10) · Patch local, before/after,
accept/reject/try-again, accept versions, reject inert ✓ · Locks Facts +
Core Meaning (+Character Logic for fiction) ✓ · Version safety incl.
reversible restore, autosave non-destructive ✓ · Writing Map read-only,
click-navigates, no private reasoning ✓ · Project create/source/task/
open ✓ · Automated tests ✓.

## 8. Limitations

- Writing Map paragraph mapping is a uniform beat→paragraph heuristic
  (read-only V0); it does not claim exact alignment.
- Mock engine text is placeholder prose (mode labeled in Settings).
- Editor is paragraph-block based; mid-paragraph drag selection is not a
  patch unit (V0 scope: paragraph range).
- Real-engine generation is synchronous (~1–2 min); the UI shows staged
  loading. No job queue in V0.
- Browser interaction was verified by endpoint parity + JS syntax check,
  not by an automated browser driver.

## 9. Deviations (recorded per AGENTS conflict rule)

1. Stack: FastAPI+SQLite+vanilla SPA instead of Next.js — explicitly
   allowed ("等价实现"), rationale in M0 review §2.
2. `PATCH /tasks/:id`, `POST /tasks/:id/sources`, `POST /tasks/:id/checkpoint`,
   `GET /tasks` added: needed for Locks persistence, workspace source
   panel and checkpointing; contract semantics unchanged.
3. Adapter composes Architect/Writer/Critic agents directly instead of
   `Pipeline.run` (which auto-runs the Critic; product Review must be
   user-initiated). No engine semantics changed.
4. Selection-scoped product patch uses a dedicated prompt
   (`prompts/product_patch.md`); `docs/06` Patch Protocol untouched.

## 10. Recommended next milestone

V0.5 candidates (not started, per stopping rule): editable Writing Map
(drag beats → re-generate affected sections), multi-reviewer blind-review
integration, project-level fact registry feeding locks automatically.
