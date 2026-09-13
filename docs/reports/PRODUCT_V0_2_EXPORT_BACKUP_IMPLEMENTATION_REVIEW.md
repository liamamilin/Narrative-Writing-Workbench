# Product V0.2 导出与备份实施评审

日期：2026-09-13。依据：[V0.2 扩展规格](../narrative-writing-product-v0.2-export-backup-spec/README.md)和[新功能开发计划](../planning/NEW_FEATURE_DEVELOPMENT_PLAN.md)。

## 产品理解

F01 解决“完成的文章怎样可靠带走，以及本地工作区怎样恢复”。它保持现有 Material → Intent → Draft → Revision → Version 主流程，只在工作台和版本历史增加出口。普通文章导出只交付标题与正文；备份面向完整工作区恢复，两者不能混成一个含内部数据的“导出”。

V0 的停止规则原本禁止自动进入后续版本；用户已明确要求规划并继续开发新功能，因此启动本增量规格。V0 的 Publishing integration 非目标仍有效：本功能只下载到本地，不连接或发布到任何外部平台。

## 实现范围与结构

| 范围 | 文件 | 决定 |
|---|---|---|
| 文本格式 | `workbench/exporting.py` | 纯函数生成 UTF-8 md/txt、可选标题和安全文件名 |
| 读取与一致性 | `workbench/service.py` | 当前稿在同一数据库临界区核对 revision；Version 只读 |
| HTTP 下载 | `workbench/api.py` | 明确媒体类型、attachment、UTF-8 文件名、no-store/nosniff |
| 产品入口 | `workbench/static/app.js` | 工作台先 flush autosave 再导出；版本页逐行导出 |
| 备份恢复 | 后续 `workbench/backup.py` | SQLite backup、manifest/hash、预检和独立路径恢复 |

当前阶段不改变数据库 schema。导出读取现有 `tasks.title`、`drafts.working_content/revision` 和 `versions.content`，不创建业务对象，不运行模型。

## API 与状态决定

- `GET /tasks/{id}/export` 要求 `expected_revision`；缺失或非法为 `REVISION_REQUIRED`，不允许“尽量导出”。
- 前端必须等待 composition、在途 autosave 和新输入全部保存；使用保存响应中的 revision 下载。
- 并发标签页先改稿时，旧 revision 返回 `STALE_BASE`。浏览器保留本地输入并不发出成功下载。
- `GET /versions/{id}/export` 读取不可变历史内容，不要求当前 revision，也不触发 Restore。
- md/txt 默认带非空任务标题；API 可用 `include_title=false` 请求原文逐字输出。

## 主要风险

1. 导出点击与 autosave 竞态：复用既有 `flushAutosave({checkpoint:false})`，服务端再次校验 revision。
2. 标题造成 Markdown 语义或响应头注入：标题压成单行，Markdown 元字符转义，文件名去除控制符、路径符号并提供固定 ASCII 回退。
3. 下载接口意外泄露内部数据：格式模块只接收正文、标题和标识，不接收 Task/Review/Operation 整体对象。
4. 活跃数据库直接复制遗漏 WAL：备份阶段必须使用 SQLite backup API，不能复用普通文件复制。
5. 恢复覆盖当前库：恢复目标必须不存在，并先完成包与 SQLite 预检。

## 测试计划

- 服务/API：正文逐字、标题规则、UTF-8、尾部空白、媒体类型、响应头、非法参数、缺失/过期 revision、无正文、未知 Version。
- 副作用：导出前后 Version、Draft revision、当前版本和 operation 不变。
- 浏览器：未等待 autosave 的手工编辑通过“导出当前稿”得到最新文本；历史 Version 下载内容正确且当前稿不变。
- 备份阶段：WAL 一致性、manifest/hash、zip 路径、大小上限、损坏库、未来 schema、完整往返和失败清理。

## 当前里程碑

E0 规格与评审完成。E1/E2 正在实现与验证。E3–E5 在文本导出独立通过并提交后开始；E6 只在两段证据齐全时完成。
