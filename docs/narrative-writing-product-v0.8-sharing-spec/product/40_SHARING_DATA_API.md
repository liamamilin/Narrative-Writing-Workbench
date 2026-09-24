# Article Sharing Data and API

## Data

`article_shares`：

```text
id, token, task_id, draft_id, draft_revision,
title, content, author, excerpt,
created_at, revoked_at
```

`title`、`content`、`author`、`excerpt` 是公开快照白名单。token 使用 `secrets.token_urlsafe(24)`，数据库唯一；`revoked_at` 非空后所有公开读取返回 404。

限制：标题 300 字符，正文 100,000 字符，署名 80 字符，摘要 240 字符。正文必须非空。创建和更新均要求 `expected_revision` 与当前 Draft 一致。

## Private API

```http
GET    /tasks/{task_id}/share
POST   /tasks/{task_id}/share
DELETE /tasks/{task_id}/share
```

`POST` 首次创建快照；已有未撤销快照且正文 revision 相同时返回原记录。传入 `replace: true` 时撤销旧快照并创建新 token。

## Public API

```http
GET /s/{token}
GET /s/{token}/meta
```

HTML 页面和 meta JSON 只从分享记录白名单组装。响应包含 `X-Robots-Tag: noindex, nofollow`、`Referrer-Policy: no-referrer`、`X-Content-Type-Options: nosniff` 和禁止嵌入策略。

卡片由工作台前端根据同一白名单数据绘制为 PNG；图片不需要读取 Task、Source 或检查接口。
