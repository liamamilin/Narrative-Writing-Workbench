# AGENTS.md

1. Product V0 是基础权威规格；本目录只增加 F05。
2. 不修改封闭的 engine internals；能力放在产品 adapter 后。
3. Prompt 外置，结构化输出经 schema 和服务端引用校验。
4. 逐段路径必须覆盖每个非空段落一次，不得静默遗漏后声称完整。
5. 不输出私有推演或确定的“真实读者感受”。
6. 问题必须复用 `revision_items` 与现有 Patch/Version 安全规则。
7. 若离线样例只得到评分复述，不开放独立入口。
