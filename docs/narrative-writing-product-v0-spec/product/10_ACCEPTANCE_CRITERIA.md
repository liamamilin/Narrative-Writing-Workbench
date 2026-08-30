# V0 Acceptance Criteria

V0 不是“UI 能打开”或“模型能生成文字”就算完成。

## Golden Path

新用户无需理解 WIR，即可完成：

1. Home
2. Start Writing
3. Choose Task
4. Add Material
5. Set Goal
6. Set basic Reader Experience
7. Generate Draft
8. Read/Edit
9. Select passage
10. Request local revision
11. Compare before/after
12. Accept/Reject
13. View version history

## Workspace

必须有：
- Sources panel
- Draft editor
- Writing panel
- Draft 在视觉上占主导

## Generation

- real engine 或明确隔离的 mock mode
- failure 不破坏 accepted text
- wrong-language output 被 repair 或安全拒绝
- 不暴露 agent logs

## Review

- 至少能展示 engine 提供的问题
- Show 能定位段落
- Fix 能进入 Patch
- 不要求 8.7/10 这种假精确评分

## Patch

必须：
- local scope
- before/after
- Accept
- Reject
- Try Again
- Accept 创建 Version
- Reject 不改变 Draft

## Locks

至少：
- Facts
- Core Meaning

Fiction：
- Character Logic

## Version Safety

- initial generation creates version
- accepted patch creates version
- history visible
- restore works
- restore reversible
- autosave 不破坏 history

## Writing Map

- read-only
- beat/progression structure
- map to paragraph
- click navigates/highlights
- 不显示 raw private reasoning

## Project

- create project
- add source
- create task
- view/open task

## Automated Tests

至少覆盖：
- create task
- generate success/failure safety
- patch propose/accept/reject
- version create/restore
- lock persistence
- writing-map serialization
- API validation
- language-safe handling

## Definition of Done

端到端可用：

```text
Material
→ Intent
→ Draft
→ Local Revision
→ Version Safety
```
