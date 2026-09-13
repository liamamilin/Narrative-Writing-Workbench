# 22 — API and Package Contract

## 文本导出 API

```text
GET /tasks/{task_id}/export
  ?format=md|txt
  &expected_revision=<integer>
  &include_title=true|false

GET /versions/{version_id}/export
  ?format=md|txt
  &include_title=true|false
```

默认值：`format=md`、`include_title=true`。当前稿必须提供 `expected_revision`；指定 Version 不需要 revision。

成功响应：

- `200`；
- `Content-Type: text/markdown; charset=utf-8` 或 `text/plain; charset=utf-8`；
- `Content-Disposition: attachment`，ASCII 回退文件名加 RFC 5987 UTF-8 文件名；
- `Cache-Control: no-store` 与 `X-Content-Type-Options: nosniff`。

产品错误：

| code | HTTP | 条件 |
|---|---:|---|
| `NOT_FOUND` | 404 | Task 或 Version 不存在 |
| `NO_DRAFT` | 409 | 当前任务没有正文 |
| `REVISION_REQUIRED` | 428 | 当前稿未提供有效 revision |
| `STALE_BASE` | 409 | 当前稿 revision 已变化 |
| `VALIDATION` | 400 | 格式或布尔选项无效 |

## 备份包（E3 目标）

扩展名暂定 `.nwb-backup.zip`，只允许：

```text
manifest.json
workspace.sqlite3
```

manifest 至少包含：格式版本、创建时间、应用 schema version、快照字节数、SHA-256、表级对象计数。恢复端只按固定文件名读取，不信任压缩包提供的路径。

凭据、settings、env、运行日志和普通文章导出不得进入备份。`writing_operations` 等本地恢复关系是否保留由完整数据库快照决定，但不得在 manifest 中复制请求正文或敏感值。
