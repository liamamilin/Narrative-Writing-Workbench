# Product V0.2 文本导出实施报告

日期：2026-09-13。范围：F01 E0–E2。本报告记录 Markdown/纯文本导出；E3–E6 后续已完成，见 [备份与独立恢复实施报告](PRODUCT_V0_2_BACKUP_RESTORE_IMPLEMENTATION_REPORT.md)。

## 交付行为

- 工作台可选择 Markdown 或纯文本并下载当前稿。
- 点击后先等待中文输入法组合结束，捕获编辑器全部段落并完成 autosave，再用返回的最新 revision 请求文件。
- 服务端在同一数据库临界区读取 Draft 并核对 revision；并发修改、缺失或非法 revision 不返回成功下载。
- 版本历史的每个不可变 Version 都可独立下载，不恢复版本、不改变当前稿、不新增 Version。
- 标题可选；无标题时正文保持原样。正文使用 UTF-8，不规范化换行、空行、尾部空白、Markdown 字符或表情。
- 下载响应提供安全 ASCII 回退与 RFC 5987 UTF-8 文件名，并设置 `no-store`、`nosniff`。

## 实现与契约

| 层 | 文件 | 责任 |
|---|---|---|
| 规格 | `docs/narrative-writing-product-v0.2-export-backup-spec/` | 范围、流程、API/包和验收标准 |
| 格式 | `workbench/exporting.py` | 纯正文渲染、标题转义、文件名清理 |
| 服务 | `workbench/service.py` | 当前 revision 原子校验、Version 只读查询 |
| API | `workbench/api.py` | 两个下载端点和产品错误 |
| UI | `workbench/static/app.js` | 保存后下载、格式选择和反馈 |
| 测试 | `tests/test_product_export.py`、`tests/browser/smoke.cjs` | 服务副作用与真实浏览器下载 |

API 与完整错误定义见[扩展契约](../narrative-writing-product-v0.2-export-backup-spec/product/22_API_AND_PACKAGE_CONTRACT.md)，实施前决策见[实施评审](PRODUCT_V0_2_EXPORT_BACKUP_IMPLEMENTATION_REVIEW.md)。

## 验证

- 导出专项：5 passed。
- 源码隔离：307 passed / 28.51 秒。
- 浏览器：B01–B11 全部通过；B11 覆盖未等待 autosave 的当前编辑、完整多段正文、历史 Version 和无副作用断言。
- Python 编译、JavaScript 语法和 `git diff --check` 通过。
- 1280×800 工作台截图已复核，新增格式选择与导出按钮未破坏正文主区域。

浏览器第一次运行在受限环境未能启动本地服务，未进入测试场景。允许本地端口与 Chrome 后完成运行；B11 第一版断言错误地把修改第一段理解为替换全文，实际下载正确保留其余段落。修正测试预期后完整通过。

## 后续状态

E3–E6 全工作区备份、manifest/hash、恢复预检及独立路径恢复已于同日完成并单独验收。DOCX/PDF、云同步、发布平台、覆盖恢复、项目级子集恢复和数据库合并仍不在本阶段。
