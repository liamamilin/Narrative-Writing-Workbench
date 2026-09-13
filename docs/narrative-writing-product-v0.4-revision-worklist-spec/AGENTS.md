# AGENTS.md — Product V0.4 Revision Worklist

先读 Product V0、本目录 README 和实现任务。

- Review 只把能用当前正文精确定位的问题建成可操作条目。
- 锚点必须含正文 hash/revision、段落范围、字符范围和原文引用；不做静默模糊匹配。
- 保留片段由用户明确标记，Patch 提案落库前及 Accept 事务内都必须确定性检查。
- AI 提案在 Accept 前不改变 Draft；跳过条目不改变 Draft。
- 同时只推进一个工作单提案；接受后其他未处理条目变为过期，不能批量套用旧 Patch。
- 接受 Patch、创建 Version、解决关联条目及更新保留范围必须在同一事务中完成。
- 手工改稿、重新生成和恢复使旧条目过期；无法可靠重定位的保留范围也必须明确过期。
- 不暴露内部 Critic JSON，不增加自动循环或全文自动修订。

每个阶段更新 `docs/reports/DEVELOPMENT_PROGRESS.md`。
