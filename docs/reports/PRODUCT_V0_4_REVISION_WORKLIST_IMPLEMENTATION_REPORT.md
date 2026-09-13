# Product V0.4 修订工作单实施报告

日期：2026-09-13。状态：W0–W6 已完成。依据 [V0.4 增量规格](../narrative-writing-product-v0.4-revision-worklist-spec/README.md)。

## 产品结果

Review 现在会把可定位问题转成修订工作单，保存严重度、具体影响、修订目标、段落范围和原文引用，默认优先展示三项。用户可定位、生成单项提案、对照、接受、拒绝或跳过；没有批量自动改写。

用户还可把连续完整段落标为“保留原文”。局部修订若会改动这些文字，服务端会明确拒绝且不创建 ProposedPatch。修改发生在保留范围之外时，接受后保留文字不变，字符位置自动重定位。

## 数据与事务

数据库 schema 从 v3 升为 v4，新增 `revision_items` 和 `preserved_spans`，`proposed_patches` 新增 `revision_item_id`。锠点由 Draft revision、内容 SHA-256、Python Unicode 字符区间和逐字 quote 组成；无法精确匹配时过期，不做相似度重定位。

Patch 接受会在同一 SQLite 事务中完成：

1. 再次校验 Draft、revision、原文切片、locks、工作单和保留范围。
2. 创建 Version 并替换目标范围。
3. 标记 Patch accepted 与当前工作单 resolved。
4. 使同轮其他可执行条目过期，重定位仍有效的保留范围。

任一写入失败时整个事务回滚。拒绝关联提案使条目恢复 open；Dismiss 只改变条目状态。手工编辑、重新生成和恢复使旧锚点失效。

备份预检保持严格表、列、索引和引用校验，同时明确接受 schema v3 和 v4。v3 包恢复到独立工作区后，下次打开会执行可回退的 v4 增量升级。

## 验证

- F03 专项：`pytest -q tests/test_revision_worklist.py` — 10 passed。
- 全量：`pytest -q` — 338 passed / 30.32 秒。
- 纯源码副本：`python3 scripts/check_clean.py` — 338 passed / 30.11 秒，不依赖私有 settings、数据库或评测素材。
- 语法：`python -m py_compile ...`、`node --check workbench/static/app.js`、`node --check tests/browser/smoke.cjs` 通过。
- Chrome 152 / Playwright 1.62.1：B01–B14 全部通过，没有未处理页面异常。B14 覆盖保留冲突拒绝、取消保留、拒绝提案后重开、接受后条目完成和新建一个版本。
- 浏览器回归额外发现并修复双击 Accept 后的异步路由覆盖竞态。
- 远程 push #27 / PR #28 在慢速 Linux runner 的 B09 失败；Accept 后刷新原先只在 `reloadTask()` 前校验路由，现改为重载前后双重校验，并用可控延迟固定该竞态。push #29–#31 / PR #30–#32 的新 ID 集合差又证明 B09 仍在操作旧任务编辑器：SPA 导航只等待 hash，旧与新页都有 `#editor`。回归现等待与 URL 任务 ID 一致的 `data-task-id` 工作区渲染后才交互。
- 修复提交 `debc4d0` 的 GitHub Actions push #33 和 PR #34 均通过，Linux/Chromium 回归闭环。

## 尚需真实使用验证

mock 可证明状态、事务和不改动保留原文，不能证明真实模型产生的 severity、effect 和 goal 总能帮用户正确排序。F03-7 仍需记录实际修稿耗时、提案接受率、接受后恢复率和用户对保留语义的理解。
