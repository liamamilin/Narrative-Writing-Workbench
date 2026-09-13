# AGENTS.md — Product V0.2 Export and Backup

先读 Product V0、Quick Write V0.1 和本目录 README，再按实现任务执行。

核心规则：

- 当前稿导出前必须完成浏览器中的待保存编辑，并由服务端核对 `expected_revision`。
- 保存失败或 revision 冲突时不得下载旧正文冒充当前稿。
- 指定 Version 导出只读，不创建 Version、不改变 Draft。
- 默认导出只含用户正文与可选标题；不得包含 WIR、模型日志、检查报告、operation、API Key 或 settings。
- 备份使用 SQLite 一致性快照，不直接复制活跃 WAL 数据库。
- 恢复必须先预检，再写入独立路径；不得覆盖当前工作库。
- 错误包、hash 不一致、路径越界、未知新版本或超限文件必须拒绝。
- 不实现云同步、发布平台、协作、项目库合并、DOCX/PDF。

每段完成后更新 `docs/reports/DEVELOPMENT_PROGRESS.md`，并保存测试与验收结果。
