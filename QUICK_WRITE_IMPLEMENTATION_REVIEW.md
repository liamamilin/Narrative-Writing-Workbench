# QUICK_WRITE_IMPLEMENTATION_REVIEW (V0.1 — Q0)

Date: 2026-08-30
Spec: `docs/narrative-writing-product-v0.1-quick-write-spec/` (extends, not
replaces, Product V0; original V0 spec remains authoritative where silent).

## 1. Understanding

Quick Write adds a third entry: **topic-only**. The missing stage is
"find something worth saying" before structure/prose:

```text
Topic → Meaning Discovery → Angle Selection → WIR → Writer → Draft → (same) Workspace
```

Meaning Discovery is structured output (3–5 genuinely distinct candidate
angles, one selected, core question, deep meaning, reader end state). It is
an internal entity: the UI shows at most a product-safe summary (topic /
selected angle / core question / reader end state) — never raw reasoning,
never the words WIR/Critic/Agent. Source-grounded and draft-revision flows
must be behaviorally unchanged.

## 2. Integration with V0 (what exists, what touches what)

| Layer | File | Change |
|---|---|---|
| DB | `workbench/db.py` | additive columns + one new table (idempotent migration) |
| Service | `workbench/service.py` | mode-aware `create_task`/`generate`, new `discover`/`rediscover_angle`/`regenerate`, factuality flag, source transition |
| Engine protocol | `workbench/engine/__init__.py` | add `discover_meaning()`; extend `generate(..., meaning=None)` |
| Real engine | `workbench/engine/real.py` | Meaning Discovery via existing `structured_call` (≤1 repair); meaning block injected into Architect input |
| Mock engine | `workbench/engine/mock.py` | deterministic discovery; records meaning into output |
| API | `workbench/api.py` | `GET /tasks/:id/meaning`, `POST /tasks/:id/rediscover-angle`, `POST /tasks/:id/regenerate` |
| UI | `workbench/static/*` | Home 3-entry cards; `#/quickwrite` screen; retry buttons in Workspace; `?v=` bump |
| Prompts | `prompts/meaning_discovery.md` | new, externalized per repo convention |
| Schema | `schemas/meaning_discovery.schema.json` | new, validated by `SchemaSet`-style jsonschema check |

Engine (`app/`) is **not modified** (V1.2 scope closed): the adapter composes
existing Architect/Writer the same way V0 did.

## 3. Meaning Discovery schema

`schemas/meaning_discovery.schema.json` (all fields required unless `?`):

```json
{
  "topic": "string",
  "surface_question": "string",
  "candidate_tensions": ["string"],
  "candidate_angles": [            // 3–5, distinct framings (minItems 3, maxItems 5)
    { "id": "A1", "label": "string", "mechanism": "string",
      "core_question": "string", "deep_meaning": "string",
      "reader_end_state": "string", "risks": ["string"] }
  ],
  "selected_angle_id": "A1",
  "selection_reason": "string",    // ranking rationale, product-internal only
  "core_question": "string",       // = selected angle's, denormalized for WIR handoff
  "deep_meaning": "string",
  "common_reading": "string",      // what a generic answer would say
  "new_reading": "string",
  "reader_end_state": "string",
  "key_tensions": ["string"],
  "constraints": ["string"],
  "fact_heavy": false,             // model-side flag (heuristic is service-side; see §8)
  "language": "zh|en"
}
```

Validation: `selected_angle_id` must reference an existing candidate id
(service-side check, beyond JSON Schema). Invalid output → **one** repair
attempt via `app/structured.structured_call` (Harness convention); second
failure → `GenerationFailed`-style retryable error, no draft touched.

## 4. Prompt / model strategy

- `prompts/meaning_discovery.md`: system prompt encoding the spec's required
  questions, candidate-quality ranking (novelty, explanatory power, emotional
  weight, expandability, progression potential, specificity), explicit
  rejection of fake depth (cliché rephrasing, vague philosophy without
  mechanism, unsupported authority), and "answer in the topic's language".
- Model/role config: reuse `config.role("architect")` (`Config.role` has no
  fallback for unknown role names; adding a new role would require touching
  `app/config.ROLE_NAMES` — engine scope closed, so reuse instead).
- No chain-of-thought: the prompt demands JSON-only output; `selection_reason`
  is a one-sentence rationale stored internally, never rendered in UI.

## 5. Angle selection strategy

One LLM call produces candidates **and** the selection (ranked per §14
criteria) — cheaper and more consistent than a second pass, since the same
model context can compare candidates directly.

- `angle_mode="auto"`: use selected angle; candidates must be distinct —
  service verifies labels differ pairwise beyond trivial paraphrase
  (normalized equality check; hard-duplicate → retryable failure).
- `angle_mode="custom"` + `custom_angle`: prompt instructs "refine this
  angle, do not overwrite it" (`Explicit User Angle > Auto Discover`); the
  custom text is stored as a candidate with `id="A0"` and force-selected.
- `Try Another Angle`: rerun discovery with an `avoid` list of previously
  selected labels injected into the user message → new discovery row.

## 6. WIR integration (Q4)

`generate(material, instruction, task_type, config, meaning=...)`:

- topic_only: `material` = topic (+ added sources if any); `instruction` =
  composed block: writing-mode guidance + `selected_angle / core_question /
  deep_meaning / reader_end_state / key_tensions` (exactly the §13 "Output
  to WIR" minimum). Architect designs beats **around this thesis**; the
  Writer receives the WIR as today, and the composed instruction carries
  "do not replace the central thesis".
- No engine prompt files change; composition happens in the adapter —
  recorded as a deviation from a hypothetical engine-native `meaning`
  parameter (engine scope closed).
- `meaning` is persisted with the plan (`engine_plans.meaning_id`), so
  review/patch/map paths keep working unchanged.

## 7. Persistence / API changes (Q1)

Migration (idempotent `ALTER TABLE ... ADD COLUMN` with duplicate-column
tolerance; new DBs get columns inline):

```text
tasks:  input_mode TEXT DEFAULT 'source_grounded'
        topic TEXT, writing_mode TEXT, angle_mode TEXT, custom_angle TEXT
engine_plans: meaning_id TEXT            (lineage: plan → discovery)
new table meaning_discoveries(
  id, task_id, topic, selected_angle_id, status('ready','failed'),
  data_json, created_at)
```

Lineage chain satisfied: `task(topic) → meaning_discoveries → selected_angle_id
→ engine_plans.meaning_id → versions.parent_version_id`.

API (extends V0 contract, same error shapes):

```text
POST /tasks                     + input_mode/topic/writing_mode/angle_mode/custom_angle
GET  /tasks/:id/meaning         product-safe summary only (4 fields)
POST /tasks/:id/rediscover-angle   → new discovery + regenerate downstream (separate path)
POST /tasks/:id/regenerate         {preserve_angle:true} → reuse latest meaning, rerun WIR+Writer
POST /tasks/:id/sources          topic_only → flips input_mode to source_grounded (persisted transition)
```

`create_task` validation: topic_only requires `topic` (instruction/material
no longer mandatory); existing modes keep V0 validation unchanged.

## 8. Factuality & source transition (Q7)

- Service-side lightweight heuristic `detect_fact_heavy(topic)`: regex for
  concrete-fact markers (years+人口/经济/裁员/股价, 灭亡/选举/战争/政策/疫情,
  specific company/org suffixes 公司/集团/政府, quantified claims 百分之/%).
  Conservative: false negatives acceptable, false positives only add a
  dismissible warning.
- Warning surfaces on create/detail (`factuality_warning` field) and in UI
  before Write: **Continue** or **Add Sources**.
- Adding a source: `input_mode` flips `topic_only → source_grounded`,
  original mode + timestamp recorded in `writing_configs.constraints_json`
  (`mode_transition`), so lineage of the transition is persisted.
- topic_only drafts never claim grounding; prompt forbids fake authority
  ("研究已经证明…" without sources), aligned with V1.2 hard gates already
  running on output.

## 9. Writing modes & UI (Q5)

`writing_mode` ∈ `deep_narrative`(默认, flagship) | `clear_essay` | `fiction`
| `free_writing`; mapped to existing task types
(`essay`/`essay`/`fiction_scene`/`free_writing`) with mode-specific guidance
text in the composed instruction. UI: Home becomes three cards (idea /
material / draft); `#/quickwrite` = topic box + mode + Angle=Auto Discover
(+advanced custom angle) + length + **Write** CTA; result routes into the
existing Workspace (no second editor). Workspace gains two topic-only
actions: "Try another angle" / "Rewrite with this angle"; after a successful
topic_only generation `locks.core_meaning` defaults ON.

## 10. Tests (Q8) — mapping to the 14 required

1–2 topic-only task + schema (mock discovery fixture) · 3 repair path via
stub client returning invalid JSON once · 4 distinctness check · 5 selected
angle persisted · 6 WIR receives meaning (spy architect input) · 7
rediscover reruns discovery (new row, avoid list) · 8 regenerate preserves
angle (no new discovery row) · 9–10 regression: existing 135 tests stay green ·
11 factuality heuristic cases · 12 source transition flips + persists ·
13 lock default ON · 14 version lineage (`meaning_id` chain).

## 11. Risks

- Real-engine latency: Quick Write adds one structured call (~topic-only
  generation ≈ two LLM calls). Mitigated by progress card (existing).
- Candidate paraphrase risk in mock/tests only; real quality is validated by
  manual acceptance (product/20), not automated.
- `structured_call` role naming: uses `role="meaning_discovery"` for logging
  but architect RoleConfig for sampling — no engine change needed.

## 12. Ambiguities & decisions

| # | Ambiguity | Decision |
|---|---|---|
| 1 | Does `Try Another Angle` auto-generate a new draft? | Yes — single user action = discovery+generate; creates a new version (parent = current), preserving V0 "AI proposes, user accepts" at version level (generation already replaces working content in V0) |
| 2 | Where does fact-heavy detection live? | Service heuristic + model-side `fact_heavy` field; UI warns before Write; never blocks Continue |
| 3 | `regenerate` without `preserve_angle`? | Treated as `preserve_angle:true` for topic_only (spec only defines the preserve path); unknown flags → VALIDATION |
| 4 | Multiple discoveries over time | All rows kept (append-only); `GET /meaning` returns latest; avoid-list uses all previously selected labels |
| 5 | Does topic_only keep `instruction`? | Optional — free-text "what you want to say" appended to the composed block; topic required |
| 6 | Writing-mode → engine task_type | Map to existing types (§9); no new engine task types (scope closed) |
| 7 | Mock engine determinism | Mock discovery = fixed 3 candidates, selects A2; respects avoid-list by cycling |
| 8 | Language | Discovery output language = topic language; expected_language config still wins for the draft |
| 9 | Home "Improve a Draft" | V0 already supports draft-revision via material+instruction; card pre-fills New Task with revision guidance text, no new pipeline (spec C flow = existing patch flow) |
| 10 | UI vocabulary | "Meaning Discovery/Angle" allowed in UI copy (user-facing concepts in this spec), but never WIR/Critic/Patcher/Architect; safety tests updated |

## 13. Milestones

Q0 this document · Q1 db+service mode/persistence · Q2 discovery (schema/
prompt/engine/mock+real) · Q3 angle selection/avoid-list · Q4 WIR handoff ·
Q5 UI · Q6 retry endpoints/paths · Q7 factuality+transition · Q8 tests ·
Q9 acceptance report.

## Addendum (2026-08-30): token-level streaming (user-requested)

Engine freeze carries an "unless explicitly requested" exception (AGENTS.md);
the user requested token-level streaming. Additive, default-off plumbing:

- `app/llm_client.py`: `generate_text(..., on_delta=None)`; OpenAIClient uses
  `stream=True` when a callback is passed (usage counters are 0 for streamed
  calls); MockClient replays the queued text in 24-char chunks.
- `app/writer.py` / `app/language.py`: optional `on_delta` forwarded; a
  language-repair retry announces `on_delta("", True)` before re-streaming.
- `workbench/engine/{real,mock}.py`: `generate(..., on_delta=None)` passthrough.
- `workbench/service.py`: `_delta_stream` batches deltas (~24 chars) into SSE
  `delta` events on the existing progress channel; flush before `done`.
- UI: `#gb-live` preview in the generation banner; reset clears it; shown
  only after the `writing` stage; final text still comes from `done` +
  reload (stream is display-only, never trusted as the artifact).

All existing callers pass no `on_delta` → behavior bit-identical (173 tests
pass, 4 new). Verified end-to-end on the real provider: 19 delta events,
reconstruction byte-identical to the persisted draft.
