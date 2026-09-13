# AGENTS.md — Product V0.3 Angle Confirmation

先读 Product V0、Quick Write V0.1、本目录 README 和实现任务，再编码。

- “先看角度”只运行 Meaning Discovery，不创建 Draft、Version 或 WIR plan。
- 候选 UI/API 只显示产品安全字段，不暴露 selection_reason、common_reading、crack 或内部执行记录。
- 用户确认必须创建不可变 meaning 快照；不得修改原 discovery。
- 确认快照必须同步候选与顶层的核心问题、深层含义、读者收获、边界和精炼命题。
- 生成只接受当前任务、当前输入、已确认用途的快照；跨任务、候选预览和过期输入必须拒绝。
- 用户编辑字段按提交值保存，确认后不得在后台再次改写。
- 一键“开始写”保持现有自动发现链路与回归覆盖。
- 不增加无限自动探索、后台模型调用或第二套正文编辑器。

每个实现阶段更新 `docs/reports/DEVELOPMENT_PROGRESS.md`。
