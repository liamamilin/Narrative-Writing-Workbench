# ANGLE_CONFIRMATION_IMPLEMENTATION_TASK

## Objective

让 Quick Write 用户在写正文前可查看 3–5 个不同角度，选择并按需编辑一个完整角度，再明确确认并生成；原有直接写流程继续可用。

## Milestones

| 里程碑 | 范围 | 完成证据 |
|---|---|---|
| A0 | 增量规格与实施评审 | 流程、用途、输入指纹、编辑字段、失败边界已记录 |
| A1 | 候选发现 API | 独立 operation；3–5 个安全候选；无 Draft/Version/plan |
| A2 | 确认快照 | 归属、用途与过期校验；不可变 lineage；字段同步 |
| A3 | 确认后生成 | confirmed_meaning_id 进入 WIR/Writer；失败后可复用 |
| A4 | Quick Write UI | 直接写、先看角度、再找一批、选择、编辑、确认 |
| A5 | 自动验收 | 服务/API、全量、浏览器和固定案例通过并记录 |

## Delivery Order

先完成 A0；A1–A3 固定数据契约和失败安全；A4 只消费该契约；A5 通过后再声明功能完成。

## Stop Conditions

- 不把模型内部推理、selection_reason、common_reading 或 crack 暴露给用户。
- 不让尚未确认的候选成为“同角度重写”的当前含义。
- 不在确认动作后隐式调用模型重新整理用户编辑。
- 不改变数据库 schema；用途、父级和输入快照写入现有 `inputs_json`。
