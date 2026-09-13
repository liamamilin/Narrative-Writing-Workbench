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

## 备份与恢复 API

```text
GET  /backups/export
POST /backups/inspect   Content-Type: application/zip
POST /backups/restore   Content-Type: application/zip
```

- `export` 返回 `application/zip`、attachment 文件名、`no-store` 和 `nosniff`。
- 两个 POST 端点直接接收 ZIP 字节，不接收客户端给出的文件名或目标路径。
- `inspect` 只返回格式/schema 版本、时间、快照大小/hash 和表对象数，不落盘工作区。
- `restore` 重新执行完整预检，再于当前数据库同级 `restored/` 下创建随机命名的新目录，返回绝对目录和数据库路径。

包上传上限 256 MiB，ZIP 中 SQLite 展开上限 512 MiB，manifest 上限 64 KiB。超出 HTTP 上限返回 `BACKUP_TOO_LARGE`/413；坏包、不支持的 schema、hash/对象数/引用不匹配返回 `INVALID_BACKUP`/400；新目录写入失败返回 `RESTORE_FAILED`/500。

## 备份包

扩展名暂定 `.nwb-backup.zip`，只允许：

```text
manifest.json
workspace.sqlite3
```

manifest 结构为：

```json
{
  "format": "narrative-writing-workbench-backup",
  "format_version": 1,
  "created_at": "<UTC ISO 8601>",
  "schema_version": 3,
  "snapshot": {
    "filename": "workspace.sqlite3",
    "bytes": 123456,
    "sha256": "<64 lowercase hex>"
  },
  "table_counts": {"projects": 1, "tasks": 2, "drafts": 2, "versions": 4}
}
```

`table_counts` 实际必须列出 schema v3 全部 15 张业务表。恢复端只按固定文件名读取，拒绝缺失、重名、多余、目录、加密或非 stored/deflated 条目，不解压 ZIP 提供的路径。

预检依次验证 manifest、字节大小、SHA-256、`PRAGMA integrity_check`、`user_version`、精确表/列集、表对象数和业务关系。视图和触发器不在当前包格式内。

凭据、settings、env、运行日志和普通文章导出不得进入备份。`writing_operations` 等本地恢复关系是否保留由完整数据库快照决定，但不得在 manifest 中复制请求正文或敏感值。
