# Product V0.4 修订工作单实施评审

日期：2026-09-13。依据 Product V0、[V0.4 增量规格](../narrative-writing-product-v0.4-revision-worklist-spec/README.md)和新功能计划 F03。

## 现状

Review 目前只把产品安全 issue JSON 存入 `reviews`；定位是段落号，没有原文引用或字符锚点。Patch 只关联 Draft，不知道对应哪项 Review 问题。保护项依赖模型和通用 locks，用户不能标记具体原文。接受 Patch 已有 revision、base version、原文切片和锁的事务校验，可作为 F03 的提交基础。

## 实现决定

- 新增规范化 `revision_items` 与 `preserved_spans`，数据库升为 v4；不把可变工作单状态塞回 Review JSON，也不把正文范围混进模型 constraints。
- Review 完成后用服务端当前正文生成精确锚点。模型位置非法的 issue 仍可作为普通诊断返回，但不创建可执行工作单。
- 真实 adapter 补回 Critic 已有的 severity/effect/action；不增加一次模型调用。mock 给出同形字段。
- 提案落库前和 Accept 事务内共用同一保留校验。相交范围无法唯一保留 quote 时拒绝，绝不依赖 Patcher 自报遵守。
- Patch 关联条目写入独立字段；Accept 同一事务创建 Version、更新 Patch、解决条目、过期其他条目并重定位保留范围。
- schema v3 备份采用版本化严格校验，不放宽任意表集合；恢复后由 Database 正常升级。

## 顺序与风险

1. W1 数据库、迁移和备份兼容。
2. W2 Review 锚点与工作单查询。
3. W3/W4 保留校验和 Patch 状态事务。
4. W5 UI 与 B14。
5. W6 源码隔离、迁移/备份往返、报告、提交和远端 CI。

主要风险是字符位置在 Unicode、空段和重复文本中漂移，以及提案生成后新增保护造成竞态。测试同时断言原文切片、字符索引、revision/hash、事务失败回滚和二次保护检查。
