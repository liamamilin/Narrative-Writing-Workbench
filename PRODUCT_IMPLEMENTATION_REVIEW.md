# PRODUCT_IMPLEMENTATION_REVIEW (M0)

Spec: `docs/narrative-writing-product-v0-spec/` (authoritative for the
product layer; older "no UI" statements superseded on 2026-08-30).

## 1. Product understanding

Narrative Writing Workbench: a desktop-web editor where the **Draft is the
center of the UI**, not chat. Golden path
`Material → Intent → Generate → Read → Review → Patch → Accept`.
Hard rule: *AI proposes, user accepts* — a ProposedPatch must never touch
the current Draft until Accept; Accept creates a Version; Reject/failure
leave content unchanged; Restore is reversible. Engine concepts
(WIR/Critic/Patcher/Architect/beat internals) stay behind the adapter and
never surface in user-facing text.

## 2. Proposed stack

`FastAPI + uvicorn + stdlib sqlite3 + vanilla-JS SPA (no build step)`

Rationale: repo is Python-only (Flask already used for the run-observer
UI); FastAPI/uvicorn/pydantic are installed; the spec explicitly allows an
equivalent simple stack ("若现有 repo 有明显更合适的简单栈,可采用等价实现")
and forbids over-engineering. A Next.js build chain would add a second
toolchain without product value in V0. Frontend = one static SPA with a
hash router served by FastAPI.

## 3. File structure

```
workbench/
├── __init__.py
├── server.py            # python -m workbench.server  → http://127.0.0.1:8600
├── api.py               # FastAPI app, routes, error shape
├── db.py                # sqlite schema + connection helpers
├── service.py           # product services: CRUD, invariants, versions, patches
├── engine/
│   ├── __init__.py      # WritingEngine protocol + get_engine()
│   ├── mock.py          # MockWritingEngine (deterministic; default in tests)
│   └── real.py          # RealWritingEngine (adapts app/ engine)
└── static/
    ├── index.html       # SPA shell + all screens
    ├── app.js           # hash router + screens + interactions
    └── styles.css       # desktop 3-column workspace
```

Tests: `tests/test_product_api.py`, `tests/test_product_safety.py`
(engine mode: mock).

## 4. Screen → route/component mapping

| screen | route | components |
|---|---|---|
| Home | `#/` | hero CTA, Recent Tasks, Recent Projects |
| New Task | `#/tasks/new` | type picker, intent, material, reader experience, constraints |
| Workspace | `#/tasks/:taskId` | SourcesPane / DraftPane / WritingPanel(Goal·Review·Locks·Settings) |
| Writing Map | `#/tasks/:taskId/map` (also in-panel switch) | read-only beat cards → highlight paragraph |
| Versions | `#/tasks/:taskId/versions` | history list + compare view (diff/inline) + Restore/Keep |
| Project | `#/projects/:projectId` | tasks list, sources list, new task |
| Settings | `#/settings` | engine mode (mock/real), minimal |

## 5. Product API → engine adapter mapping

| API | adapter call | real engine | mock engine |
|---|---|---|---|
| `POST /tasks/:id/generate` | `engine.generate(material, instruction, task_type, config)` → `{text, plan}` | ArchitectAgent → WIR → WriterAgent(expected_language, target_length) → language repair (docs/17) → fidelity gates | fixed template text + fixed plan |
| `POST /tasks/:id/review` | `engine.review(text, material, instruction, plan, config)` → product summary+issues | CriticAgent; critique mapped to Strong/Good/Needs-attention + positioned issues | deterministic issue set |
| `POST /tasks/:id/patch` | `engine.patch(text, selection, instruction, locks, context)` → `{after}` or lock-conflict error | new `prompts/product_patch.md` (selection-scoped, lock-aware, fail-safe) | deterministic transform of selection |
| `GET /tasks/:id/writing-map` | `engine.writing_map(plan, text)` → beats + paragraph ranges | WIR beats → paragraph mapping (heuristic, read-only) | plan passthrough |

`plan` (EnginePlan.data_json) stores internal WIR; UI never receives it raw.

## 6. Persistence

SQLite file `workbench/workbench.db` (override via `WORKBENCH_DB`).
Tables = spec 06 objects: projects, sources, tasks, task_sources,
writing_configs, engine_plans, drafts, versions, proposed_patches, reviews.
Invariants enforced in `service.py`: one active Draft per task;
current_version belongs to draft; rejected patch never writes content;
restore = new version pointing at old content (reversible); locks persisted
in writing_configs.locks_json and recorded on every patch row.

## 7. State management

Server is the single source of truth; frontend keeps a small client store
per task (task, draft, versions, patches, review). Autosave: debounced
`PATCH /drafts/:id {working_content}` (never creates versions). Versions
only at checkpoints: generation / accepted patch / explicit checkpoint /
restore.

## 8. Test plan (pytest + TestClient, mock engine)

- project/source/task creation + validation errors
- generate success → version(source_type=generation), draft set
- generate failure safety → existing draft untouched, retryable error shape
- language-unsafe mock → repair or GENERATION_FAILED (never wrong-language draft)
- patch propose → status proposed, draft unchanged; accept → new version +
  splice; reject → unchanged; try-again → second proposal
- version list/compare/restore; restore reversible; autosave doesn't version
- locks persist; lock-conflict patch → fail-safe error, no change
- review → issues with paragraph positions; Show/Fix wiring (fix → patch)
- writing-map serialization product-safe (no raw WIR keys)
- API validation (unknown ids, bad payloads)

## 9. Milestones

M0 review (this file) → M1 skeleton (db+api+SPA shell) → M2 Home/New Task →
M3 Workspace layout → M4 generation → M5 local patch → M6 versions →
M7 review → M8 writing map → M9 project → M10 tests+acceptance+report.

## 10. Ambiguities & decisions (minimal-compat interpretations)

1. **Pipeline.run auto-runs Critic** but product Review must be
   user-initiated → adapter composes ArchitectAgent/WriterAgent/CriticAgent
   directly instead of Pipeline.run. (No engine semantics changed.)
2. **Engine patch protocol is whole-draft critique-driven**; product patch
   is selection-scoped → dedicated `product_patch.md` prompt; docs/06
   untouched.
3. **Critique issue locations are beat ids, not paragraphs** → map
   beat→paragraph via the same heuristic used by writing-map; unmapped
   issues anchor to whole draft.
4. **Settings screen** has route but no screen spec → minimal V0 settings
   (engine mode + saved-state info), no model/temperature exposure on
   other screens.
5. **Upload**: `uploaded_file` source type accepted; V0 reads text files
   only (.txt/.md), others rejected with product-safe error.
6. **Whole-draft revision scope selector** (spec 05): V0 implements it as
   paragraph-range selection presets (selection / affected sections /
   entire draft) on the patch endpoint.
7. Language repair failure surfaces as retryable `GENERATION_FAILED`
   per spec 05 failure behavior.

## 11. Technical risks

- Real-engine latency (~1–2 min/generation) → generate runs in a worker
  thread; task status `generating`; UI shows product loading stages.
- Vanilla SPA size creep → keep components flat; no framework.
- SQLite concurrency → single-writer via `check_same_thread=False` +
  threading lock; V0 desktop-scale is fine.
