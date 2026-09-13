# REVISION_WORKLIST_IMPLEMENTATION_TASK

## Objective

把一次 Review 变成最多优先展示三项、可定位、可逐项修改或跳过的工作单；用户可标记正文范围为保留片段，系统确定性阻止修改提案破坏这些文字。

## Milestones

| 里程碑 | 范围 | 完成证据 |
|---|---|---|
| W0 | 增量规格与实施评审 | 锚点、状态、事务、迁移、备份兼容与失败边界已记录 |
| W1 | schema v4 与迁移 | 新旧库升级、回退备份、v3/v4 备份预检通过 |
| W2 | Review → 工作单 | 可定位 issue 持久化；优先级、引用和过期可查 |
| W3 | 保留片段 | 创建、查询、删除；提案和接受双重保护 |
| W4 | Patch 状态事务 | proposed/resolved/dismissed/stale 与 Version 一致 |
| W5 | 工作台 UI | 三项优先问题、定位、保留、逐项修改、跳过与状态反馈 |
| W6 | 验收与报告 | 专项、全量、迁移/备份、浏览器 B14 通过 |

## Stop Conditions

- 不批量生成或接受多个旧 revision 的 Patch。
- 不用相似度或模型猜测重定位重复文本。
- 不允许客户端声称某段受保护；服务端必须从当前数据库验证。
- 不让 schema v4 升级使已创建的 v3 备份失去恢复能力。
