# Reader Path Data and API

## Engine Output

```text
overview
steps[]:
  id, paragraph, paragraph_quote, primary_function,
  knowledge_gain, question_raised?, question_answered?
issues[]:
  id, type, severity, paragraph_start/end,
  quote, message, effect, goal
```

步骤必须覆盖所有非空段落且不重复。服务端验证段落号、完整段落 quote、问题范围和逐字 quote；不可靠问题不创建工作单。

## Persistence

`reviews.analysis_type` 区分 `writing` 与 `reader_path`。路径检查复用 Review 的 revision/hash/operation 快照与 `revision_items`，新增 `reader_path_steps` 保存逐段产物。普通写作 Review 查询必须筛选 `analysis_type=writing`。

## API

```http
POST /tasks/{task_id}/reader-path-review
GET  /tasks/{task_id}/reader-path-review
```

返回：`id / revision / stale / overview / steps / issues`。问题的定位、跳过和 Patch 继续使用 revision item API；Patch 请求带 reader-path review id 和 revision item id。
