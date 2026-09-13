# 25 — Angle Confirmation Data and API

## Discovery 用途元数据

`meaning_discoveries` 保持 append-only。`inputs_json` 使用向后兼容包裹：

```json
{
  "purpose": "angle_options | automatic | confirmed",
  "task_inputs": {"topic": "...", "writing_mode": "..."},
  "task_fingerprint": "sha256",
  "discovery_inputs": {"topic": "...", "engine": {}}
}
```

旧行没有 `purpose` 时视为 `automatic`。确认行另含 `parent_discovery_id`、`selected_candidate_id` 和 `selection_source`。预览用途不会被当前 meaning、同角度重写或 resume 当成可用含义。

## API

```text
POST /tasks/{task_id}/angle-options
GET  /tasks/{task_id}/angle-options?discovery_id=<id>
POST /tasks/{task_id}/confirm-angle
POST /tasks/{task_id}/generate  {"confirmed_meaning_id": "<id>"}
```

`POST angle-options` 只接受 topic-only task，无 Draft。成功返回 `operation_id`、`discovery_id`、`stale=false` 和安全候选。GET 返回同一安全投影，并相对当前任务输入计算 `stale`。

安全候选字段固定为 `id`、`label`、`mechanism`、`core_question`、`deep_meaning`、`boundary`、`reader_end_state`；不返回完整 meaning JSON。

确认请求：

```json
{
  "discovery_id": "mean_...",
  "candidate_id": "A1",
  "edits": {
    "label": "...",
    "core_question": "...",
    "deep_meaning": "...",
    "boundary": "...",
    "reader_end_state": "..."
  }
}
```

`edits` 缺省时使用候选原值；出现时必须恰好包含全部五个字段，每项为去除首尾空白后 1–2000 字符。确认快照把 `selected_angle_id`、上述 candidate 字段，以及顶层 `core_question`、`deep_meaning`、`boundary`、`reader_end_state`、`new_reading`、`refined_thesis` 同步；原 discovery 不变。

错误码：`NOT_FOUND`/404、`VALIDATION`/400、`ANGLE_OPTIONS_REQUIRED`/409、`STALE_ANGLE_OPTIONS`/409、`WRONG_TASK`/409、`CONFIRMED_MEANING_REQUIRED`/409。
