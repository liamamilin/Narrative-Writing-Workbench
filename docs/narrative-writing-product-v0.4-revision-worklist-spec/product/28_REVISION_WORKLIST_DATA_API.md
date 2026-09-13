# 28 — Revision Worklist Data and API

## 数据

schema v4 新增：

- `revision_items`：review/draft、原 issue id、base revision/hash、段落与字符范围、quote、类型、严重度、诊断、影响、修改目标、状态、patch_id、时间。
- `preserved_spans`：draft、base revision/hash、段落与字符范围、quote、`active|stale`、时间。

条目状态为 `open | proposed | resolved | dismissed | stale`。历史 Review 与条目保留；产品默认读取最新 Review。

## API

```text
GET    /tasks/{task_id}/revision-worklist
POST   /revision-items/{item_id}/dismiss
POST   /tasks/{task_id}/preserved-spans
GET    /tasks/{task_id}/preserved-spans
DELETE /preserved-spans/{span_id}
```

创建保留范围提交 `expected_revision` 与 `selection.paragraph_start/end`。响应返回产品安全锚点，不返回全文或模型内部结果。

现有 `POST /tasks/{id}/patch` 可增加 `revision_item_id`。服务端从条目读取并核对 selection、review、quote 和目标；不能用跨任务条目。关联提案只使用条目的 `goal` 作为默认修改要求，用户可显式补充但不能换到别的正文范围。

错误使用既有 `REVISION_REQUIRED`、`STALE_BASE`、`STALE_REVIEW`、`LOCK_CONFLICT`，新增 `STALE_ITEM`、`ITEM_IN_PROGRESS`、`PRESERVED_TEXT_CONFLICT`。

## 备份兼容

新备份记录 schema v4 与新增表。检查器同时认识严格的 v3 和 v4 表/列/索引集合；v3 包恢复为原始 v3 数据库，首次由 Workbench 打开时执行现有升级备份和 v4 migration。
