# Product V0.3 写前角度确认实施评审

日期：2026-09-13。依据 Product V0、Quick Write V0.1、[V0.3 增量规格](../narrative-writing-product-v0.3-angle-confirmation-spec/README.md)与[新功能计划](../planning/NEW_FEATURE_DEVELOPMENT_PLAN.md)。

## 理解与范围

用户需要可选的写前决策点：一次发现只给候选，不提前写正文；确认一个完整 angle meaning 后才进入现有 WIR/Writer。原有“一键开始写”是独立旁路，不能因新功能增加等待或确认。

本轮完成 A0–A5。UI 复用 Quick Write 和 Workspace；不增加新的正文编辑器、数据库 migration、自动循环或确认后的隐式模型调用。

## 现状与一致性决定

- 当前 `discover()` 同时承担调用、校验、持久化和安全进度投影；可增加用途参数复用，避免第二套 discovery 实现。
- 当前 `meaning_discoveries.inputs_json` 保存裸 discovery 输入。新行改为带用途的包裹；读取同时支持旧格式，数据库保持 schema v3，V0.2 备份格式不变。
- 当前“无 Draft 的最新 discovery”会成为 current meaning。需要排除 `angle_options`，否则未确认候选会污染同角度重写和摘要。
- candidate 当前缺少单独 boundary。schema 以可选字段向后兼容扩展，prompt/mock 为新输出补齐；安全投影要求每张卡都有 boundary，并可回退到顶层 boundary 以兼容结构化输出修复期。
- 确认通过复制原 data 构造新快照，不修改被引用的历史产物。用户编辑一次提交完整字段，避免只改标题而 Writer 仍读旧含义。

## 文件结构与顺序

1. `meaning_schema.py`、JSON schema、prompt/mock：候选安全投影和完整卡字段。
2. `service.py`、`api.py`：用途、指纹、候选、确认、确认后生成。
3. `app.js`、`styles.css`：Quick Write 卡片及 AUTOSTART payload。
4. `tests/test_angle_confirmation.py`、浏览器 B13：契约与用户路径。
5. 开发日志、全量测试、提交和远端 CI。

## 风险与验证

- 最大风险是预览 discovery 被旧逻辑误用。通过用途过滤、current meaning/续跑回归验证。
- 第二风险是输入变化后错误复用。使用只含用户可变输入的稳定 SHA-256，并在查询、确认、生成三处核对。
- 第三风险是确认字段不同步。测试同时断言持久化 JSON、engine 收到的 meaning 和 plan lineage。
- 失败安全用故障 Writer 验证：确认行保留、无 Draft，带同一 confirmed id 重试不再 discovery。
