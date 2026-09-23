# Product V0.8 文章分享实施报告

日期：2026-09-23。状态：工程实现完成。

## 交付结果

工作台正文工具栏在“版本”之后新增“分享”。创建前先完成 autosave 并校验 Draft revision，随后生成独立、不可变的文章快照。分享面板提供作者署名、摘要、卡片预览、链接复制、系统分享、1080×1440 PNG 卡片下载、打开文章与停止分享。

公开链接打开独立阅读页：中文衬线正文、窄阅读栏、响应式标题与移动端间距。页面不依赖工作台 SPA，也不显示编辑、素材和模型信息。

## 数据与接口

- SQLite schema 升至 v8，新增 `article_shares`；每个 Task 同时最多一个有效分享，历史撤销记录保留到 Task 删除。
- `GET/POST/DELETE /tasks/{id}/share` 管理当前分享；创建和更新必须提交当前 `expected_revision`。
- `GET /s/{token}` 返回文章 HTML，`GET /s/{token}/meta` 返回公开字段。
- 24-byte 随机 token 提供至少 192-bit 随机性。更新分享会撤销旧 token 并生成新 token；停止分享、删除 Task 或删除 Project 后旧链接返回 404。
- 分享快照进入 v8 严格备份；v3–v7 备份保持可读，v7 数据库可升级到 v8，Task/Draft 关系错误会被拒绝。

## 公开边界

公开 JSON 采用白名单组装，仅包含：

```text
title, content, author, excerpt, created_at, reading_minutes
```

它不包含 share/task/draft/version 标识、revision、素材、写作目标、保护项、检查、operation、模型配置或 API Key。正文与元信息经过 HTML 转义。公开响应带 `noindex,nofollow`、`no-referrer`、`nosniff`、禁止 iframe 的 CSP 与 `no-store`。

## 验证

- `python -m pytest -q`：393 passed / 33.43 秒。
- JavaScript 语法与 Python 编译通过；`git diff --check` 通过。
- Google Chrome / Playwright：B00–B19 全部通过，无未处理页面异常。
- B19 覆盖创建分享、localhost 提示、公开页访问、PNG 卡片下载、编辑后旧快照不变、更新后旧链接 404、新链接显示新正文、停止分享后 404。
- 专项测试覆盖公开字段精确集合、脚本转义、revision 冲突、字段上限、替换 token、撤销、Task 删除、v7→v8 迁移、v8 备份与错误关系拒绝。

## 已知边界

分享链接使用当前浏览器 origin。通过 `127.0.0.1` 或 `localhost` 访问时，链接只在本机有效，界面会明确提示；要让他人或手机跨设备访问，需要把 Workbench 部署到可访问的域名。当前没有账户和访问名单，持有链接即可阅读；需要收回时应停止分享或更新链接。

本版本不包含评论、协作、推荐流、搜索收录、阅读统计、第三方平台代发布或服务端生成社交平台专用图片。
