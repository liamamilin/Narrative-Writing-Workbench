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

## Addendum (2026-08-31): in-task param fixes, streaming race & gate sweep

User-reported: (1) editing intent/immersion/explicitness/length then
Regenerate had no effect; (2) streaming felt poor; (3) a confusing
"did not pass a safety check" failure. Root causes and fixes:

Params (three layers): frontend sent `null` on generate → now sends the five
Goal-panel controls; `/generate` ignored a body → `_apply_param_overrides`
persists+validates (dials low/med/high, length 100–5000) before running;
`real.py` consumed only target_length → `_dial_block` now feeds the three
experience dials into the architect+writer instruction.

Streaming: SSE `/progress` raced the POST (client connects before status
flips to generating) → 2s grace loop that follows the channel-object swap on
reset; `_delta_stream` batch 24→8 chars; reconnect no longer doubles text
(seq dedupe in `openProgress`); a typewriter pacing layer smooths fast
providers.

Gate (T0, engine touch — explicit user request): the hard gate resolved
expected_language from the *seed topic*, so an English topic with Chinese
discovery prose failed `expected_language_match` (the "safety check" error).
`real.py:resolve_language_for` now probes the Meaning Discovery text for
topic-led pieces; `app/gates.py:hard_gates` gains an opt-in
`allow_new_facts` flag (default False → bit-identical for source-grounded
runs) so topic-led fiction isn't failed for invented numerals/quotes/names.
Gate failures now log full `failure_reasons` and surface a human zh message.

Robustness: non-`EngineError` (transport) no longer strands status='generating'
(→ failed + SSE error); stale-generating retry runs before param writes;
regenerate/rediscover share the concurrency guard; autosave flushes +
deduped checkpoint before a destructive regenerate; diffHtml drains tails;
target_length validated at create/patch/override.

Spec note: engine freeze carries the "unless explicitly requested" exception
(AGENTS.md); the two `app/` edits (gates.py flag, and the earlier streaming
plumbing) are additive and default-preserving. 188 tests pass (10 new).
Verified on the real provider: English topic + auto language + Chinese prose
→ status ready, 97 delta events, all four stages.

Same sweep also cleared the T3 tier: runGeneration now guards against
navigation mid-run (tid capture), settings report the running adapter name
and roll back to mock on a failed hot-swap, an explicit empty instruction
clears it, MockWritingEngine gains an opt-in `simulate_repair` reset signal,
test_connection accepts empty keys for local providers, pending patches
(before/after) survive reload, AUTOSTART is bound to its target task, the
writing-map tab handles errors, and cancelling the fact-heavy confirm opens
the created task instead of orphaning it. 194 tests pass (16 new).

## Addendum (2026-08-31): intermediate-stage token streaming

User request: discovery/structure/review each call the LLM and previously
showed only a static stage line. Approved third engine-freeze exception
("unless explicitly requested", AGENTS.md): `app/llm_client.py`
(`generate_structured` gains `on_delta`; OpenAI path streams with automatic
non-stream fallback on provider rejection of stream+response_format),
`app/structured.py` (`structured_call` forwards `on_delta`, incl. the repair
attempt; omitted kwarg for legacy fakes), and `app/architect.py` /
`app/critic.py` (`run(..., on_delta=None)` pass-through). All additive,
default-preserving; 201 tests pass (7 new).

Product layer: new SSE kinds `stage_summary` (always on) and `stage_delta`
(only when `settings.stream_debug` is on, default off). `stage_summary`
carries human-readable Chinese lines derived from validated structures —
discovery (angle + core question), structure (beat `meaning_gain` chain via
`_outline_summary`), review (dimension labels + issue count). UI shows them
in a collapsible 过程流 section; the raw-JSON token panes sit behind the
调试原始流 checkbox.

Spec judgment recorded: Product V0 says UI must not expose WIR/Critic
internals. Plain-text previews (angle, outline gains, quality labels) are
treated as user-facing summaries, not internal leakage; raw JSON reaches the
UI only through the explicit debug switch, mirroring the existing
draft-stream behavior. Review now runs on the task SSE channel
(reset per review; done/error/close semantics identical to generate).

## Addendum (2026-08-31): intermittent architect failures — root cause fix

Symptom: generations intermittently died at the WIR stage with
"The draft could not be generated correctly."; logs showed repeated
`architect: invalid structured output`.

Root cause: `config.live.yaml` set `structured_mode: none` for
architect/critic — a V1.2-era workaround for a gateway stall with
reasoning models under `response_format: json_object`
(V1_IMPLEMENTATION_REPORT.md §4). In free-text mode deepseek-v4-flash
intermittently emits invalid/schema-violating WIR JSON; the single
spec-mandated repair (docs/01 §7) sometimes still fails → GenerationFailed.

Fix (config only, no code): live probe confirmed the gateway now handles
`json_object` for deepseek-v4-flash (valid JSON, faster than plain), so
architect/critic moved to `structured_mode: auto` (provider rejection
still falls back automatically). `max_output_tokens` 4000→6000 as
truncation insurance. Verified: 2/2 architect runs clean without repair;
full generate+review e2e green (one schema-repair cycle exercised and
recovered).

## Addendum (2026-09-03): bug sweep of the stage-streaming work

B1 (race, both directions): `Service.review()` reset the task SSE channel
without checking for an in-flight generation; a review started during
generate (second tab or direct API) orphaned the generation stream — and
vice versa, since review never sets the DB status the generate guard could
not see it. Fixed: review calls `_guard_not_generating` (409 GENERATING)
and registers the task in an in-memory `_reviewing` set (crash-safe: dies
with the process); generate/rediscover/regenerate reject while a review is
in flight (409 REVIEWING). The UI disables #r-run during generation and
the generate buttons during review.

B2 (fallback preemption): with `structured_mode: auto`, `_create`'s internal
APIStatusError handler dropped `response_format` while still streaming, so
`generate_structured`'s non-streaming JSON fallback never ran — debug
streaming silently lost the JSON constraint. Fixed: response_format is only
dropped by the internal handler for non-stream calls; stream rejections now
propagate to the outer fallback (non-stream + json_object).

B3 (concatenated debug panes): the schema-repair attempt streamed into the
same sink as the invalid first attempt. Fixed with the established
`on_delta("", reset=True)` protocol (app/language.py): structured_call
announces the reset, `_stage_stream` emits a flagged `stage_delta` and
clears its buffer, the UI raw pane clears on reset. Single-arg sinks keep
working (TypeError fallback).

B5/B6 (hygiene): mock discovery no longer emits debug tokens before raising
DiscoveryFailed; `stream_debug` now parses "false"/"0"/"no"/"off" as False
and "" as keep-current (was `bool(value)`, where "false" → True).

Not fixed (documented, low impact): streaming GenerationResult carries no
usage tokens (B4, debug path only); the SSE grace loop waits 2s before
replaying a fast completed review (B7, mock-only latency, replay correct);
runReview's EventSource is not closed on navigation (B8, self-terminates on
eof/300s cap). 209 tests pass (8 new).

## Addendum (2026-09-04): idle auto-shutdown

User request: the nohup'd workbench server outlived every browser session.
New `workbench/idle.py`: `IdleTracker` (monotonic clock, lock-guarded
touch), HTTP middleware touching it on every request start (SSE opens
count; no browser polling exists to keep it wedged), daemon watchdog with
poll = clamp(timeout/4, 1s, 15s), exit via SIGINT to self (uvicorn graceful,
`timeout_graceful_shutdown=5` so an open SSE tab cannot block the stop).
`WORKBENCH_IDLE_TIMEOUT` minutes, default 30, 0 disables; startup banner
shows the mode. Engine/product logic untouched. 213 tests pass (4 new) +
live smoke: request refreshes the clock, server self-exits with a visible
message.

## Addendum (2026-09-11): topic suggestion on Quick Write (design review)

User request: on the Quick Write page ("What do you want to talk about?"),
help the user arrive at a high-value topic (e.g. 勤劳是奴隶的道德), fill
it in, then hit Write. Decisions confirmed with the user: 3 candidates per
click, two-level taxonomy, each candidate shown with a one-line hook,
implement now.

Research grounding (taxonomy design, not copied): NYT Learning Network
prompt collections classify by surface domain (Technology & Social Media /
School / Identity & Family / Arts / Health / Ethics); IELTS Task-2 families
(Education, Technology, Society, Work, Media, …); philosophy's perennial
questions (self, justice, truth, beauty, time); the Chinese essay tradition
of 人与自我 / 人与社会 / 人与自然. Key insight for this product: a topic
like 勤劳是奴隶的道德 is not a subject, it is an *inversion* of a virtue
inside a domain — so the taxonomy's second level must be the debatable
*tension* (张力轴), not a topic list. Hybrid scheme: 一级=生活领域
(recognizable anchor), 二级=领域内的张力轴.

Data model: static `workbench/taxonomy.json` (versioned in-repo, no admin
UI; 8 domains × 6 tensions, ascii ids). Served at GET /taxonomy; POST
/topics/suggest {domain?, sub?, avoid[]} → {topics:[{text, hook}]} ×3.
Taskless endpoints (suggestion happens before task creation). Mock engine
serves deterministic canned candidates so the flow works keyless; real
engine runs a structured call (prompts/topic_suggest.md, schema-validated
with one repair, avoid honored). Hard rule preserved: AI proposes, user
accepts — candidates only fill the topic input on click; Write still
requires the user's own click. UI: two-level chips (一级 chips + 二级
chips + 不限 default), candidate chips with hook subtitles, 换一批
accumulates avoid; no framework dependencies, vanilla chips per existing
styles.css.

Implemented (2026-09-11): `workbench/taxonomy.json` (8 domains × 6 tensions,
ascii ids), `prompts/topic_suggest.md` (3 debatable single sentences + hooks,
filler/inversion/safety rules), `workbench/topic_schema.py` (exactly 3,
distinct, 4-40 chars, hook 2-24, banned filler), engine protocol
`suggest_topics(domain, sub, avoid, config)` — mock serves a 48-item canned
pool with per-call rotation and strict avoid filtering; real engine runs a
schema-validated structured call (role topic_suggest, architect cfg, one
repair). Service validates category ids against the taxonomy and wraps
engine failures as retryable TOPIC_SUGGEST_FAILED. Endpoints: GET /taxonomy,
POST /topics/suggest (taskless, nothing persisted). UI: two-level chips
(不限 default; sub row appears on domain pick), 给我一个话题 → candidate
chips (text + hook subtitle) that fill the topic input on click, 换一批
keeps a 9-item seen window as avoid. 226 tests pass (7 new); live smoke
against the real engine returned valid trios for 不限 and work/diligence.

## Addendum (2026-09-11): taxonomy v2 (World Topic Taxonomy V1.0) + search box

User supplied `world_topic_taxonomy_v1.md` (faceted topic-discovery system)
and asked to rebuild the picker on it, plus a search box. Decisions
confirmed: Patterns stay prompt-only (no third selector); the source doc
moves into the repo (`docs/TOPIC_TAXONOMY.md`); search = single input
filtering both dropdown options by substring.

- `workbench/taxonomy.json` v2: `domains` = §1 Surface Domains (49, flat,
  ascii ids — domain↔tension no longer nested); `tensions` = §6 global
  goal-conflict axes (t01–t33). Remaining facets (Object/Relation/
  Phenomenon/Mechanism/Pattern/Scale/Time/Inquiry) are prompt vocabulary,
  not UI.
- `prompts/topic_suggest.md` rewritten around the new system: Concrete
  Anchor → Puzzle structures (§12) → Pattern Library (§10, all 60, prompt
  -only) → internal TVS screening (§13 hard gates) → anti-pseudo-depth
  filter (§14) → diversify → output best 3. Schema widened to 6–60 chars
  (puzzle sentences run longer than aphorisms); hook ≤ 24 (target ≤ 20).
- API: `POST /topics/suggest {domain?, tension?, avoid[]}` — `sub` kept
  as a legacy alias for `tension`; domain/tension validated independently
  against the taxonomy.
- Mock engine: canned pool rebuilt as multi-domain-tag entries (93 items);
  coverage invariant tested (every domain ≥3, every tension ≥2); rotation
  + avoid unchanged. Real engine passes domain + tension into the prompt.
- UI: chips replaced by two native selects (领域 49 / 张力 33, "不限"
  default) + one search input filtering both selects live (keeps current
  selection visible); candidate chips (text + hook) unchanged. cache-bust
  app.js v29.
- 230 tests pass (test file rewritten for v2; coverage invariant keeps the
  canned pool honest).

## Addendum (2026-09-11): Object Taxonomy joins the picker (taxonomy v3)

User asked where the Object Taxonomy went — it had been prompt-only
vocabulary. Per the source design (§15 Concrete Anchor), objects ARE the
"具体入口", so they now join the UI: taxonomy.json v3 adds `objects`
(§2, 18 O-groups × 313 anchors, name-keyed since objects repeat across
groups). UI becomes three orthogonal searchable selects — 领域 (49
Surface Domains) / 对象 (313, optgrouped by O-group) / 张力 (33) — one
search box filters all three. API accepts `object` (validated against
the anchor name set); engine protocol gains `object_name`; real prompt
uses it as the Concrete Anchor requirement; mock filters canned topics
by substring (anchor heuristic, unmatched objects roam). 230 tests pass.

Follow-up (same day): live-engine hardening for topic suggestion.
(a) Reasoning-mode empty output: the architect role cfg (reasoning_effort
low + long prompt + json_object) intermittently returned empty content on
this gateway — same bug family as V1 report §4. `RealWritingEngine
.suggest_topics` now derives a lite cfg (reasoning_effort="", max tokens
3000, temperature 0.6) via dataclasses.replace; verified live: ~19s,
valid trio, no repair.
(b) Occasional single-schema-error reruns (model writes long puzzle
sentences): schema text cap widened 60→80 chars; prompt prefers 10–45,
hard cap 70. Live smoke: object=算法 / 大学 both return Pattern-hooked
trios (Goodhart / Individual Rationality Trap / Hidden Beneficiary).
Note: "加班"/"学生" are not in the source Object list (§2) and are
correctly rejected by validation — pick from the 313 anchors.

## Addendum (2026-09-11): Topic Picker v4 — domain is the only UI facet;
topics are batch-produced

User simplified the model after seeing v3: objects and tensions are
*production resources*, not UI facets. The picker now exposes only the
domain (49 Surface Domains); taxonomy v3 stays in-repo as the engine's
production vocabulary.

Design:
- **Batch generation**: one click produces `count` topics (default 8,
  API allows 3..12). New topics APPEND to the list (user's revised
  choice; a 清空 button resets list + dedup memory). Already-shown texts
  accumulate into `avoid[]` (capped 40 client-side, 16 injected into
  the prompt) so every batch is genuinely new.
- **Coverage enforcement** (source doc §0 "Taxonomy 负责不遗漏世界"):
  (1) prompt hard-requires a different Concrete Anchor per topic and
  batch-wide spread across the domain's sub-areas — no eight rewrites
  of one object; (2) the real engine samples `count` distinct tension
  axes from taxonomy §6 and assigns one per topic; (3) a batch-level
  soft hint lists the M1–M10 mechanism families so the batch's "why"
  shapes differ too (soft, not per-topic assignment — three hard
  constraints per topic proved over-constraining in design review).
- **User steer**: optional 方向提示 input (`hint`, ≤100 chars) feeds
  generation without letting the whole batch collapse onto one object.
- **API**: POST /topics/suggest gains `count` (int 3..12, else 400) and
  `hint`; `object`/`tension` remain accepted for compatibility (UI no
  longer sends them). Engine protocol gains count/hint.
- **Schema**: topics 3–12 (was exactly 3), distinct-text check kept,
  text 6–80, hook 2–30 (headroom; prompt still prefers ≤20).
- **Mock**: serves `count` from the canned pool with rotation, capped
  at pool size so a batch never self-repeats; 4 canned hooks exceeded
  24 chars (English Pattern names) and were shortened.
- Engine imports its own taxonomy loader (no upward service import).

Live smoke (real engine): education batch 1 = 8 topics on 8 distinct
sub-areas (分科/手机禁令/导师制/成绩问责/小组作业/学区房/集体备课/重点校
经费), 8 distinct axes; batch 2 (avoid batch 1) zero overlap and new
sub-areas; labor+hint 关注外卖骑手 honored without collapsing the batch.
Occasional single-schema-error reruns remain possible (retryable UX);
hook headroom reduced their rate.

Docs: docs/TOPIC_TAXONOMY.md == world_topic_taxonomy_v1.md (verified
byte-identical); taxonomy.json v3 verified anchor-exact against the
source (49 domains / 18 groups / 313 anchors / 33 tensions).
235 tests pass.

## Addendum (2026-09-11): Quick Write v5 — two-pane redesign + client-side
topic library

User review of the v4 page found the core content (generated topics)
buried mid-form. v5 restructures the page around the discovery flow:

- **Two-pane layout**: left = discovery (searchable domain chips cloud +
  optional steer + generate button + topic library, independently
  scrollable); right = compose (topic textarea, writing mode, angle,
  length, language, 开始写) as a sticky column. <1000px collapses to one
  column with compose first.
- **Topic library (client-side)**: generated topics persist in
  localStorage (`qw_topic_lib_v1`, FIFO 200, degrade gracefully in
  private mode). Items carry {domain, domainName, text, hook, ts}; the
  library renders grouped by domain in collapsible sections ("挂在领域
  后面"), each with a count badge and a per-domain 再来一批 button
  (avoid stays global). Server storage remains zero — "AI proposes,
  user accepts" untouched; Write still requires the user's click.
- **Curation & feedback**: click card fills the right pane + selected
  state (+✓); hover ✕ removes a single topic (title shows its
  timestamp); stats header (n 条 · m 个领域); empty-state guidance;
  skeleton shimmer cards during generation; failed button becomes ↻ 重试;
  new batch fades in and scrolls into view.
- **avoid = whole library** (was last 40): engine prompt injection cap
  raised 16→24; mock already filtered by the full list.
- **Compose state persists** (`qw_compose_v1`): topic/mode/angle/length/
  language survive reloads; ⌘/Ctrl+Enter triggers 开始写.
- **Copy unified to Chinese** across Quick Write and Home (hero, entries,
  Recent Tasks/Projects); examples replaced — "谈谈失败。" violated the
  anti-pseudo-depth filter the coach itself enforces; nav gets an active
  state. Cache-bust app.js?v=32 / styles.css?v=11.
236 tests pass.

## Addendum (2026-09-11): v5.1 — seed mode (relevance) + skeleton fix

Two user-reported issues from live use:

1. **Skeleton kept shimmering after success** — the skeleton cards were
   hidden only on the error path; success never hid them. Fixed by
   moving the hide into `finally`.
2. **Low relevance: user-typed input ignored by generation.** The user
   typed a phenomenon ("女人会爱上伤害她的男人…") into the topic box and
   clicked generate — but generation only read domain + steer, and the
   prompt actively barred narrowing the batch to the user's input.
   Fix: **seed mode**. When the topic box is non-empty, its content is
   sent as `seed` (≤200 chars, else 400) and the button reads
   "✦ 围绕它生成一批" (mode made visible via input listener). Engine:
   seed present → no sampled tension axes; the prompt instructs the
   model to diagnose the seed's Puzzle/mechanism/tension internally and
   produce every topic as a **different facet of that same structure**
   (distinct instances/mechanisms/scales — never reworded). Without a
   seed the roam mode is unchanged (spread + sampled axes). Steer box
   kept (seed takes precedence). Mock filters its pool by seed
   substring (roams on no match).
3. Also: schema dup-check now normalizes quote/punctuation variants
   (curly vs straight quotes are the same text — live batch had shown
   quote-flipped twins).
Live smoke (real engine, seed = the user's own sentence): all 8 topics
press on the trauma-bond structure from distinct facets (intermittent
reinforcement / costless-good devaluation / exit cost / effort
rationalization / common enemy / arousal misattribution / definition
right / pseudo-intimacy). No domain drift, no paraphrases.
240 tests pass.
