# API Contract

实现可以 REST/RPC/server actions，但要保持下面的产品语义。

## Projects

```http
POST /projects
GET  /projects
GET  /projects/:id
```

## Sources

```http
POST /projects/:projectId/sources
```

## Tasks

```http
POST /tasks
GET  /tasks/:id
```

Create Task 示例：

```json
{
  "project_id": null,
  "type": "fiction_scene",
  "title": "Father and Son Dinner",
  "instruction": "父亲不要直接表达支持。",
  "material": "...",
  "source_ids": [],
  "config": {
    "expected_language": "zh",
    "immersion": "high",
    "explicitness": "low",
    "intensity": "medium",
    "target_length": 800,
    "locks": {
      "facts": true,
      "core_meaning": true,
      "character_logic": true
    }
  }
}
```

## Generate

```http
POST /tasks/:id/generate
```

Response：

```json
{
  "task_id": "task_123",
  "draft_id": "draft_123",
  "version_id": "version_1",
  "content": "...",
  "status": "completed"
}
```

不得返回 private reasoning。

## Review

```http
POST /tasks/:id/review
```

产品层 response：

```json
{
  "summary": {
    "progression": "strong",
    "meaning_density": "strong",
    "immersion": "good",
    "restraint": "needs_attention",
    "coherence": "strong"
  },
  "issues": [
    {
      "id": "issue_1",
      "location": {
        "paragraph_start": 4,
        "paragraph_end": 4
      },
      "type": "over_explanation",
      "message": "This paragraph may explain more than the reader needs.",
      "fixable": true
    }
  ]
}
```

不要把内部 Critic JSON 原样暴露。

## Patch

```http
POST /tasks/:id/patch
```

Request：

```json
{
  "base_version_id": "version_3",
  "selection": {
    "paragraph_start": 4,
    "paragraph_end": 4
  },
  "instruction": "Make this less explicit.",
  "locks": {
    "facts": true,
    "core_meaning": true
  }
}
```

Response：

```json
{
  "patch_id": "patch_12",
  "before": "...",
  "after": "...",
  "status": "proposed"
}
```

Accept：

```http
POST /patches/:patchId/accept
```

Reject：

```http
POST /patches/:patchId/reject
```

Reject 不得修改 Draft。

## Writing Map

```http
GET /tasks/:id/writing-map
```

返回 product-safe structure：
- beat id
- function
- reader_before
- reader_after
- meaning_gain
- paragraphs

不得返回 chain-of-thought。

## Versions

```http
GET  /drafts/:id/versions
GET  /versions/:id
POST /versions/:id/restore
```

## Autosave

可用：

```http
PATCH /drafts/:id
```

## Error Shape

```json
{
  "error": {
    "code": "GENERATION_FAILED",
    "message": "The draft could not be generated correctly.",
    "retryable": true
  }
}
```
