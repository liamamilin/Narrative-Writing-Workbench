# Interaction Specification

## Core Rule

```text
AI proposes, user accepts.
```

## Generate Draft

点击 `Generate Draft` 后：
- accepted draft 保持安全
- 生成失败不得破坏已有正文
- UI 只显示产品级状态

推荐 loading：
- Preparing the draft...
- Understanding your material
- Designing progression
- Writing the draft

不要显示 Architect/WIR/Critic 等内部对象。

## Selection Revision

用户选择文字后出现：

```text
Revise | Shorter | Less Explicit | More Natural | More Immersive
```

Revision UI：
- Presets
- Custom instruction
- Preserve surrounding text
- Preserve meaning
- Preserve facts（如适用）

CTA：`Generate Patch`

## Patch Proposal

展示：

```text
Before
...

After
...
```

操作：
- Accept
- Reject
- Try Again

只有 Accept 后才创建新 Version 并更新 current draft。

## Review

Issue card 包含：
- plain-language diagnosis
- location
- Show
- Fix

Show → 定位/高亮
Fix → 局部 Patch

## Whole-Draft Revision

Scope：
- Selected paragraphs
- Affected sections only
- Entire draft

默认 `Affected sections only`。

## Locks

### Facts
不改变 source facts。

### Core Meaning
保持核心解释/意义。

### Character Logic
保持既定人物行为逻辑。

### Structure
保持当前 progression。

### Wording
尽可能保留成功措辞。

若不能满足 Lock，应 fail safely，而不是静默违反。

## Autosave

手工编辑：
- Saving...
- Saved

不要每个 keystroke 创建一个版本。

## Version Creation

有意义的 checkpoint：
- initial generation
- accepted AI patch
- explicit checkpoint
- restore

## Failure Behavior

Generation fail → current content unchanged  
Patch fail → current content unchanged  
Review fail → draft remains usable  
Language repair fail → show retryable generation error
