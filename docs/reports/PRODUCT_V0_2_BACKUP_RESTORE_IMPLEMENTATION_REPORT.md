# Product V0.2 备份与独立恢复实施报告

日期：2026-09-13。范围：F01 E3–E6。E0–E2 文本导出证据见 [文本导出实施报告](PRODUCT_V0_2_EXPORT_IMPLEMENTATION_REPORT.md)。

## 交付行为

- 设置页可下载全工作区 `.nwb-backup.zip`，包内固定只有 `manifest.json` 和 `workspace.sqlite3`。
- 快照通过 SQLite backup API 生成，能纳入已提交的 WAL 页；目标快照转为单文件 DELETE journal 模式。
- manifest 记录包格式、UTC 时间、schema v3、快照字节数/SHA-256 和 15 张业务表对象数，不复制正文、请求或凭据。
- 上传后先预检；换文件会使之前结果失效。只有预检通过后 UI 才允许恢复，确认后服务端仍重新做完整预检。
- 恢复使用受控的 `restored/` 根目录和随机新目录。快照先写临时目录并复验，再用目录 rename 落盘；失败删除临时目录，当前库始终不变。

## 预检边界

校验包括：ZIP 总大小、展开文件大小、固定文件集、压缩/加密方式、manifest 类型与版本、快照 hash/大小、SQLite 完整性、schema 版本、精确表/列、对象数，以及 Project、Source、Task、Draft、Version、Plan、Meaning、Patch、Review、Operation 和 Generation Result 间的必要引用与同任务/同草稿归属。

上限为 256 MiB 上传包、512 MiB SQLite 快照和 64 KiB manifest。客户端不能指定恢复路径，ZIP 条目不会按其自带路径解压。

## 实现与验证

| 层 | 产物 |
|---|---|
| 核心 | `workbench/backup.py`、`Database.backup_to()` |
| 服务/API | `Service` 备份方法，`/backups/export|inspect|restore` |
| 产品入口 | 设置页“本地数据”卡片 |
| 自动验收 | `tests/test_product_backup.py`，浏览器 B12 |

- 备份专项：10 passed，覆盖 WAL、隐私排除、篡改、缺文件、多文件/路径、SQLite 损坏、未来 schema、断链、上限、往返、失败清理和 API。
- 源码隔离全量回归：317 passed / 28.94 秒；JavaScript 语法与 `git diff --check` 通过。
- 桌面 Chrome：B01–B12 全部通过；B12 核对下载文件名、预检前按钮状态、预检摘要、独立目录/数据库和当前 Draft 不变。
- 实现提交 `8160170` 已推送到 `codex/v0-1-stabilization`；GitHub Actions push [#19](https://github.com/liamamilin/Narrative-Writing-Workbench/actions/runs/34745056754) 1 分 39 秒通过，PR #2 [#20](https://github.com/liamamilin/Narrative-Writing-Workbench/actions/runs/34745058407) 1 分 35 秒通过。

## 使用恢复副本

恢复完成后，页面会显示新目录。停止当前 8600 服务后，可在仓库根目录指向返回的数据库启动：

```bash
WORKBENCH_DB="<restored_directory>/workbench.db" python3 -m workbench.server
```

如需与当前工作区同时对照，可另用 `WORKBENCH_PORT=8601`。备份不携带模型设置或密钥；恢复数据与运行配置是两个独立概念。

## 限制

当前是全工作区备份，不支持项目子集、合并、覆盖、云同步或在 UI 中热切换数据库。跨机器手工迁移与真实大型数据库压力验收尚未由用户完成。
