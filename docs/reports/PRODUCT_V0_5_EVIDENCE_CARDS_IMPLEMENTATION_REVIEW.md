# Product V0.5 论点与素材依据卡实施评审

日期：2026-09-13。依据 Product V0、[V0.5 增量规格](../narrative-writing-product-v0.5-evidence-cards-spec/README.md)和新功能计划 F04。

## 产品理解

F04 帮助用户回答“这句关键陈述基于哪段已提供材料”。它不是联网事实核查，也不把模型或用户确认包装成外部认证。第一版只服务 source-grounded 的分析与观点写作，并把原句、材料引文和限定条件直接给用户核查。

## 实现决定

- 在产品 adapter 增加 `check_evidence()`，Mock 与 Real 同形；Real 用独立外置 prompt 和 JSON Schema，不改封闭的 engine internals。
- 数据库升为 v5，使用 `claim_checks` 与 `claim_links` 保存检查快照、精确锚点、关系及独立用户状态。
- Source 快照按稳定排序保存 ID 与 SHA-256；当前 Source 集合、内容或 Draft revision/hash 不一致即整轮过期。
- 模型输出先过 schema，再由服务端做确定性引文校验。无有效 Source 锚点时绝不保留 `supported/conflict`。
- 局部处理复用 F03 ProposedPatch/Accept/Reject，不创建第二套修改或版本机制；Patch 新增可选 `claim_link_id`。
- UI 复用右侧“检查”页，写作问题和依据检查保持两个明确动作；卡片直接展示关系文字、正文原句和素材原句。

## 文件与里程碑

主要修改：`workbench/evidence_schema.py`、`workbench/schemas/evidence_check.schema.json`、`prompts/evidence_check.md`、engine adapter、`db.py`、`backup.py`、`service.py`、`api.py`、前端静态文件、专项测试和浏览器 B15。

顺序为 E1 输出契约与样例，E2 adapter，E3 持久化与过期，E4 API/Patch，E5 UI，E6 全量验收与报告。

## 风险与测试

核心风险是模型引用不存在的原句、重复文本定位歧义、把推断错标为支持、Source 更新后继续使用旧结论，以及依据卡 Patch 绕过当前 revision。专项测试覆盖非法引用降级、跨任务 Source、Unicode/重复文本、输入上限、正文/材料过期、用户状态分离、Patch 安全、并发检查、v4 备份升级与 v5 严格备份。真实模型的误报、漏报和核查时间另行人工评估。
