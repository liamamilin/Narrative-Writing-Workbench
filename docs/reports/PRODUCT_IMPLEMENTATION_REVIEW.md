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

## 2026-09-12 Product polish pass

Scope: preserve the current Python/FastAPI/SQLite and no-build SPA. No new
writing modes, research features or comparative quality evaluation.

Findings: new-material/revision forms discard input on navigation; goal
changes PATCH the server but leave WS.task stale; experience controls reset
on tab changes; conflicting selected options and an inaccurate timeout
fallback confuse defaults. Product patch prompt contradicts the adapter's
existing full-draft context.

Implementation: restore browser-local compose forms by mode/project; serialize
and flush task goal saves before navigation/tab changes and intent suggestions;
clarify optional controls/defaults and product copy; correct the external patch
prompt's context/output contract. Existing API/data model and patch acceptance
semantics remain authoritative. Browser form recovery is not a version.

Validation: focused existing product tests, JS syntax, and offline browser
interaction checks for restoration, goal persistence and patch workflow. No
live model calls or writing-quality claims. Record outcomes in the product
implementation report. Main risk: async saves/navigation; failed goal saves
must keep the user on the page with inputs intact.

## 2026-09-13：稳定性开发启动（S00–S08）

用户已要求开始开发并定期记录进展。执行范围为规划中的现有产品稳定性收口；新功能 F01–F09 保留为后续候选。进展记录于 `DEVELOPMENT_PROGRESS.md`，每个里程碑、重要验证后更新，长阶段至少每 30 分钟记录一次。

### 实施决定

- 保留 FastAPI / SQLite / 无构建 SPA，主要修改 `workbench/`、测试、开发脚本与文档；不变更引擎语义。
- 增加显式短事务句柄。校验、版本插入、正文更新与补丁终态在同一事务内完成；模型调用放在事务外。
- Draft 增加 revision。autosave、checkpoint、restore、已有稿件的生成以及 patch proposal 必须携带 expected_revision；缺失返回明确的刷新提示。accept 使用提案内持久化的 base_revision 检查，重复接受仍返回 409。
- 生成完成后根据开始时的 revision 条件提交；冲突保存生成产物，不能覆盖已更新正文。
- Version 增加 engine_plan_id、restore_source_version_id；patch/checkpoint 继承基稿 plan，restore 继承被恢复版本 plan。旧版本来源无法证明时保留为空。
- Review 绑定正文 hash/revision 与配置快照；当前稿件结构查询和失败续跑结构查询分开。修改后旧诊断不能直接定位修稿。
- 长操作采用单进程有界运行登记、operation 标识与持久终态，启动后标记中断，不自动继续模型调用。设置变更只作用于后续操作。
- 前后端同批更新写入契约；既有测试使用显式 revision 测试辅助，新契约、并发及故障测试独立验证缺失/过期 revision。
- 验证先使用合成数据、临时库、mock/可控 adapter；真实模型效果与人工盲评单列，不能以 mock 测试替代。

### 文件与接口

`workbench/db.py`：事务与增量迁移；`service.py`：写入一致性、来源与运行状态；`api.py`：revision/状态契约；`static/app.js`：保存冲突、设置及状态恢复。按职责需要添加轻量辅助模块，不整体改写框架。

测试新增产品提交安全、版本来源、运行恢复与浏览器主流程案例；公共合成 benchmark fixture 置于 `tests/fixtures/`。干净环境测试不读取忽略的私人研究数据或真实设置。

风险：旧页面与新 API 的契约切换、数据库迁移、长操作状态与前端保存交错。迁移先在临时旧库演练；保留已有未提交变更快照；不使用运行中的用户数据库验证。

### 浏览器验收追加决定：旧稿导入（2026-09-13）

B03 发现旧实现将 `draft_revision.material` 仅作为 Source 保存，随后 Generate 全文，违背 Quick Write `product/12_INPUT_MODES_SPEC.md` 的 Draft → Diagnose → Patch 契约。修正为创建任务时原子保存原稿及 `manual_checkpoint` 初始版本，来源 plan 为空；UI 默认检查页且隐藏全文生成。该模式的 Generate API 返回明确冲突，要求检查/局部修订。保留四种既有 version source_type，不将导入稿伪标为 AI generation。
