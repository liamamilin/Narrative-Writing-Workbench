# User Flow

## Golden Path

```text
Home
↓
Start Writing
↓
Choose Task Type
↓
Add Material
↓
Set Intent
↓
Generate Draft
↓
Read
↓
Review / Select Passage
↓
Patch
↓
Compare
↓
Accept
↓
Version Saved
```

## New User

不强制先创建 Project：

```text
Home → Start Writing → New Task → Workspace
```

## Returning User

```text
Home → Recent Task → Workspace
```

## Generation

用户看到：

```text
Material + Intent → Generate → Draft
```

内部可以：

```text
Material + Intent + Constraints
→ Architect
→ WIR
→ Writer
→ Fidelity Gate
→ Draft
```

但 UI 不展示 agent 名称。

## Review

```text
Draft
→ Review
→ Issue
→ Show
→ Highlight
→ Fix
→ Patch Proposal
→ Accept/Reject
```

## Manual Revision

```text
Select Text
→ Revision Toolbar
→ Preset / Custom Instruction
→ Generate Patch
→ Diff
→ Accept / Reject / Try Again
```

## Writing Map

V0：

```text
Workspace → Writing Map → Click Beat → Highlight Paragraph
```

只读，不做 drag-and-drop 编辑。

## Safety / Agency

AI 不得静默：
- 替换 accepted text
- 接受自己的 patch
- 删除历史版本
- 改变 project facts
