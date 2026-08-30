# Screen Specification

V0 六个核心 Screen。

## 1. Home

目标：尽快开始写。

主 CTA：`Start Writing`
次 CTA：`New Project`

显示：
- Recent Tasks
- Recent Projects

不显示 Model / Temperature / WIR / Critic。

## 2. New Task

使用单页 progressive form，不强制 wizard。

Task Type：
- Fiction Scene
- Narrative Analysis
- Character Analysis
- Essay
- Emotional Retelling
- Free Writing

字段：
- What do you want this writing to do?
- Material
- Upload
- Add from Project

Reader Experience：
- Immersion
- Explicitness
- Intensity
- Target Length

Constraints：
- Preserve Facts
- Preserve Core Meaning
- Avoid Over-Explanation
- Do Not Invent Major Events

Primary CTA：`Create & Write`

## 3. Writing Workspace

桌面三栏：

```text
┌──────────────┬──────────────────────────────┬──────────────────┐
│ Sources      │ Draft                        │ Writing Panel    │
│ ~20%         │ ~55%                         │ ~25%             │
└──────────────┴──────────────────────────────┴──────────────────┘
```

### Left
- Task Material
- Project Sources
- Notes
- Add Source

### Center
- Title
- Saved state
- Draft / Writing Map switch
- Version selector
- Editable draft

必须支持 text selection、paragraph selection、undo、autosave。

### Right
Tabs：

```text
Goal | Review | Locks | Settings
```

## 4. Writing Map

只读 explainability。

每个 Beat 显示：
- function
- reader_before
- reader_after
- meaning_gain
- mapped paragraphs

点击 Beat → Draft 定位 + 高亮。

禁止显示 raw WIR JSON 或 private chain-of-thought。

## 5. Version History / Compare

History：
- version
- time
- origin
- revision reason

Origin：
- Initial Generation
- Manual Checkpoint
- AI Patch
- Restore

Compare：
- Before / After 或 inline diff
- Restore
- Keep Current

## 6. Project

显示：
- Project Name
- New Writing Task
- Tasks
- Sources

V0 不做复杂知识图谱、时间线、协作。
