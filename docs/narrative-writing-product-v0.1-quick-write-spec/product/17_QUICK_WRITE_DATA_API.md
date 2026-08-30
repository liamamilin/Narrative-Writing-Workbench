# Quick Write Data and API Specification

## Task Extension

Add:

```text
input_mode:
  topic_only
  source_grounded
  draft_revision
```

## Topic-Only Task Fields

Suggested:

```text
topic
writing_mode
angle_mode
custom_angle?
reader_experience
target_length
expected_language
```

## MeaningDiscovery

Internal entity:

```text
id
task_id
topic
selected_angle_id
data_json
created_at
```

## Candidate Shape

```json
{
  "id": "A1",
  "label": "Failure revalues the past",
  "core_question": "Why does failure change the meaning of previous effort?",
  "deep_meaning": "Failure damages the framework that justified prior sacrifice.",
  "reader_end_state": "The reader sees failure as retrospective reinterpretation, not only loss."
}
```

## Create Task

```http
POST /tasks
```

Example:

```json
{
  "input_mode": "topic_only",
  "type": "essay",
  "topic": "为什么人会怀念已经结束的关系？",
  "writing_mode": "deep_narrative",
  "angle_mode": "auto",
  "config": {
    "expected_language": "zh",
    "target_length": 900,
    "immersion": "high",
    "explicitness": "low"
  }
}
```

## Generate

Reuse:

```http
POST /tasks/:id/generate
```

Behavior:

```text
topic_only:
  Meaning Discovery → Angle → WIR → Writer

source_grounded:
  existing source pipeline

draft_revision:
  revision pipeline
```

## Product-Safe Meaning Summary

Optional:

```http
GET /tasks/:id/meaning
```

Return only:
- topic
- selected angle
- core question
- reader end state

No hidden reasoning trace.

## Another Angle

Possible:

```http
POST /tasks/:id/rediscover-angle
```

## Rewrite Same Angle

Possible:

```http
POST /tasks/:id/regenerate
```

Request:

```json
{
  "preserve_angle": true
}
```

## Lineage

Persist:

```text
topic
meaning_discovery_id
selected_angle_id
engine_plan_id
draft_version_id
```
