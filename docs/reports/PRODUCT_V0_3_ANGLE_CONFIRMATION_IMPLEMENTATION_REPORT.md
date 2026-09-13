# Product V0.3 写前角度确认实施报告

日期：2026-09-13。
规格：`docs/narrative-writing-product-v0.3-angle-confirmation-spec/`。
实施评审：`PRODUCT_V0_3_ANGLE_CONFIRMATION_IMPLEMENTATION_REVIEW.md`

## 结果

Quick Write 保留“一键开始写”，新增“先看角度”：一次明确操作只发现 3–5 个候选，不创建正文；用户用卡片选择、按需编辑完整角度并确认后，原 Workspace 才使用不可变确认快照生成正文。

## 实现

- Meaning candidate 增加每个候选自己的 boundary；prompt 同时要求候选自己的 crack 与 strongest counterexample，避免切换候选时沿用胜出候选的内部论证。
- `POST/GET angle-options` 返回固定安全字段；`POST confirm-angle` 校验任务归属、候选 id、完整编辑字段和当前输入指纹。
- 沿用 schema v3 的 `meaning_discoveries.inputs_json` 保存 `automatic`、`angle_options`、`confirmed` 用途和父级，不增加数据库迁移，不改变 V0.2 备份包。
- 未确认 options 不会成为 current meaning，也不会进入同角度重写或生成续跑。确认后生成显式携带 `confirmed_meaning_id`；Writer 失败后的继续操作可复用相同 meaning 和已完成 plan。
- UI 提供原生键盘可用的候选按钮、完整编辑区、“再找一批”和“确认并开始写”；表单变化立即废弃页面上的旧候选。

## API 与错误边界

新增：

```text
POST /tasks/{id}/angle-options
GET  /tasks/{id}/angle-options?discovery_id=...
POST /tasks/{id}/confirm-angle
POST /tasks/{id}/generate { confirmed_meaning_id }
```

跨任务、非预览 discovery、未确认 discovery、错误 candidate 和过期输入分别用稳定 4xx 拒绝。候选响应不含 `selection_reason`、`common_reading`、`new_reading`、`crack`、反例或执行内容。

## 验证

- 新增 `tests/test_angle_confirmation.py`，覆盖只发现不写、输出安全、未确认隔离、直接写旁路、再找一批、不可变确认、完整字段同步、WIR 精确交接、跨任务/非法/过期拒绝、失败续跑和 custom angle。
- Python 全量：328 passed。
- JavaScript 语法、Python compile、`git diff --check` 通过。
- Chrome B01–B13 通过；B13 用键盘选择第二张卡、编辑五项字段、确认后生成，并核对 Workspace 当前 meaning 与 Draft。

## 效果边界

固定 mock 流程证明编排、调用次数、追溯和失败安全；它不能判断候选是否真的减少“写完再换角度”。真实模型候选质量、用户总等待、换角度次数和最终保留率需要后续真实使用记录或人工试用，本轮不把自动化通过解释为效果提升。
