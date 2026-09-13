# Product V0.5 论点与素材依据卡实施报告

日期：2026-09-13。状态：E0–E6 已完成。依据 [V0.5 增量规格](../narrative-writing-product-v0.5-evidence-cards-spec/README.md)。

## 产品结果

有材料的观点、叙事分析和人物分析任务现在可以单独执行“检查材料依据”。结果以关键陈述卡呈现，明确展示正文原句、陈述类型、材料关系、判断说明、可用的 Source 原句与局部处理目标。

用户可定位正文、查看对应素材、确认关联、本轮忽略，或发起局部修改。“确认关联”只保存用户核查状态，不改变 `supported / inference / insufficient / conflict` 关系，也不被描述为外部事实认证。修订继续生成 ProposedPatch；接受前正文不变，拒绝不创建 Version。

## 结构化检查与确定性校验

产品 engine adapter 新增 `check_evidence()`。Real adapter 使用外置 `prompts/evidence_check.md` 和 Draft 2020-12 JSON Schema；Mock adapter 提供相同接口。输入只包含当前 Task 显式关联的 Source，并设置正文 20,000 字符、20 份 Source、材料总计 60,000 字符和最多 12 张卡的边界。超限明确拒绝，不静默截断。

模型结果落库前由服务端再次验证：

1. 正文段落范围有效，`draft_quote` 在范围内只有一个逐字匹配。
2. Source ID 属于当前任务，`source_quote` 在对应 Source 中只有一个逐字匹配。
3. 无可靠材料锚点的 `supported` 或 `conflict` 降为 `insufficient`，并清除虚假材料引用。
4. 无法可靠定位的正文陈述不生成可操作卡。

这些规则证明引文存在和定位可靠，不声称模型对支持关系的判断必然正确。

## 数据、过期与修订安全

数据库 schema 从 v4 升为 v5，新增 `claim_checks` 与 `claim_links`，ProposedPatch 新增 `claim_link_id`。检查快照保存 Draft revision/hash，以及全部关联 Source 的 ID、role 和内容 hash。读取、确认、忽略、提案和接受时都会比较当前快照；正文编辑/生成/恢复/接受 Patch、Source 内容变化或 Source 集合变化都会使旧检查过期。

依据卡 Patch 强制使用卡片段落范围，并复核正文精确 quote。Accept 事务还会复核当前 Draft、Source 快照、锁和 Patch 关联。接受后新正文自动使旧依据检查过期；拒绝清除卡片的提案关联并保持正文不变。

严格备份预检现支持 v3、v4 和 v5。v5 增加 claim/check/source/patch 关系完整性检查；恢复旧 schema 后由 Database 执行有备份、可回退的增量升级。

## 界面

右侧“检查”页把“检查写作问题”和“检查材料依据”分成两个动作。依据卡使用文字关系标签，直接显示正文与材料原句；定位正文会回到中栏并高亮段落，查看素材会在左栏高亮对应 Source。过期结果可回看，但不再显示确认、忽略或处理动作。

## 验证

- F04、F03、备份与运行事务专项：42 passed。
- 全量：`pytest -q` — 349 passed / 31.34 秒。
- 纯源码副本：`python3 scripts/check_clean.py` — 349 passed / 33.15 秒；不依赖用户 settings、数据库或私人评测材料。
- `python3 -m py_compile ...`、`node --check workbench/static/app.js` 和 `git diff --check` 通过。
- 本地 Google Chrome / Playwright 1.62.1：B01–B15 全部通过，无未处理页面异常。B15 覆盖检查、素材定位、用户确认、局部提案、接受前正文不变、接受后新建一个 Version 和旧检查过期。

## 尚需真实使用验证

自动化证明输入边界、引用锚定、状态和修订安全，不能证明真实模型不会误判材料关系或漏掉重要陈述。F04-7 仍需用已建立的正反样例和真实文章分别记录错误支持、遗漏、用户核查时间、修订接受率，并据此决定是否扩展到研究辅助或项目事实清单。
