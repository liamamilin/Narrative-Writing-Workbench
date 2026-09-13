# 26 — Acceptance Criteria

- 候选发现产生 3–5 个可辨别候选和一个已完成 operation，不产生 Draft、Version 或 engine_plan。
- 候选响应不含 selection_reason、common_reading、new_reading、crack、内部日志或模型调用内容。
- 非 topic-only、有 Draft、跨任务 candidate、错误 candidate id、预览快照直接生成均被拒绝。
- 话题、模式、自定义角度或相关配置变化后，GET 标记旧候选 `stale=true`，确认与生成拒绝。
- 确认会追加新行并保存父 discovery、候选和选择来源；原始 data_json 字节不变。
- 用户提交完整编辑后，candidate 与顶层对应字段完全一致，WIR 收到确认后的值。
- 确认后生成不再次调用 discover；Writer 失败不删除确认快照，用同一 id 重试仍不 discovery。
- Quick Write 可用键盘完成选择、编辑和确认；“再找一批”不会自动循环。
- 直接“开始写”仍通过原有 Quick Write 回归。
- 全量 Python、JavaScript 语法、浏览器 B01–B13 和固定 mock 案例通过。
