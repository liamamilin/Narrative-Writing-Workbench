# Product V0.7 本地选题箱实施报告

日期：2026-09-13。范围：F06-1～F06-5。规格：[Product V0.7](../narrative-writing-product-v0.7-idea-box-spec/README.md)。

## 完成结果

Quick Write 现在把模型刚生成的候选放在“本次生成”，刷新后允许消失；只有用户点击“收藏”后，话题才进入本机 SQLite 选题箱。用户也可以收藏手工输入的话题，搜索话题、备注或领域，编辑备注，在待写/归档间整理，并从未关联选题开始写作。关联后的条目标记为已写并打开原任务。

旧 `qw_topic_lib_v1` 会在进入 Quick Write 时按最多 200 条提交给迁移接口。服务端先完整校验，再在单个事务中按标准化话题导入并返回 received/imported/existing；客户端只在两类计数之和等于 received 时删除旧 key。失败、超限或确认不完整时保留原数据。

## 数据与一致性

- SQLite schema 从 v6 升至 v7，新增 `ideas` 及状态/任务索引；文件库升级前生成 `.pre-v7-*.sqlite3` 一致性备份。
- 标准化固定为 Unicode NFKC、连续空白折叠、trim 与 casefold。只合并标准化后相等的话题，不做语义去重。
- `POST /tasks` 接受可选 `idea_id`。topic-only、标准化话题相等和未关联校验，与 Task 创建及 Idea 更新在同一事务完成；失败不会留下半个 Task 或错误关联。
- `written` 必须有 Task；有 Task 的选题不能回到 `to_write`。归档既可用于待写条目，也可用于已关联条目。
- v7 备份包含 Ideas，预检校验状态与 Task 关系；v3–v6 的严格契约继续可恢复，并由 Workbench 正常升级。

## 接口与界面

新增接口：

```text
GET   /ideas?q=&status=&limit=
POST  /ideas
PATCH /ideas/{idea_id}
POST  /ideas/import-legacy
```

Quick Write 新增“收藏当前话题”“本次生成”“选题箱”、关键词搜索、状态筛选、备注编辑、用于写作和打开文章。建议卡继续支持键盘选择；收藏行为是单独按钮，不会因选择候选而自动持久化。

## 验证

- F06 专项 10 项通过：标准化去重、长度/来源边界、字面搜索、状态、原子迁移、任务关联失败安全、v6→v7 和 v7 备份关系。
- 全量 Python：`369 passed`。
- JavaScript：`node --check workbench/static/app.js` 与浏览器脚本语法通过。
- Chrome 152 / Playwright 1.62.1：B01–B17 全部通过，无未处理页面异常。
- B17 实际覆盖旧库迁移、服务端确认后删 key、候选不落库、明确收藏、搜索、备注、清空 localStorage 后重载、创建关联任务、已写过滤和打开原任务。

## 限制与下一步

选题箱是单机工作区数据，没有账户、云同步、标签系统、语义搜索或自动热点抓取。当前下一优先级仍是真实浏览器人工走查与 F02–F05 真实模型效果评估；F07 是否启动由两稿比较的真实需求决定。
