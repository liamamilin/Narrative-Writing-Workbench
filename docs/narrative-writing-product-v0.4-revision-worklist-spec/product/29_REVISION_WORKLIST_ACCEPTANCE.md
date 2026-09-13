# 29 — Revision Worklist Acceptance

- Review 只为合法段落范围建条目；每项 quote 与字符索引逐字对应当前正文。
- 工作单按 major、moderate、minor、fatal 的产品规则排序，其中 fatal 最高；默认只突出前三项，历史仍可查看。
- 重复段落、Unicode、表情、连续空行的锚点不串位。
- 手工编辑、重新生成、恢复、目标或素材变化后旧 open/proposed 条目不可继续生成或接受。
- 创建/删除保留范围不改变 Draft revision 或 Version。
- 破坏保留文字的模型输出不产生 ProposedPatch；提案后新增保留范围时，Accept 再次阻止冲突。
- 不相交 Patch 接受后保留范围仍 active，字符位置按差值更新且 quote 不变。
- 关联 Patch proposed/reject/accept 分别使条目变为 proposed/open/resolved；Accept 的 Version 与状态更新原子一致。
- Dismiss 不改变正文；同一工作单不允许两个 proposed 条目。
- UI 可定位、保留、取消保留、处理、对照、接受/拒绝/跳过；无批量自动执行。
- schema v3 数据库升级到 v4；v3 与 v4 备份均可严格预检和恢复。
- 全量 Python、浏览器 B01–B14 和失败注入通过。
