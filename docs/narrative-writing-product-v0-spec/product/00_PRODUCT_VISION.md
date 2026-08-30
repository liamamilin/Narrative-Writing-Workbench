# Product Vision

## Positioning

Narrative Writing Workbench。

面向“已经有内容/素材/想法，但不满意普通 AI 写作”的用户。

核心问题：

> 我知道自己想说什么，但不知道怎样把它写得真正有效。

## Value Proposition

输入：

```text
Material + Intent + Constraints
```

输出：

```text
结构有效、可控、可局部修改的 Draft
```

产品能力：

```text
Understand → 理解想表达什么
Structure  → 组织读者如何一步步理解
Write      → 生成自然、有推进的正文
Revise     → 只修改该修改的部分
```

内部可映射到 Meaning / WIR / Writer / Critic+Patcher，但普通用户不应看到这些实现概念。

## Differentiation

普通 AI：

```text
Prompt → Text
```

本产品：

```text
Material
→ Intent
→ Structured Writing
→ Inspect
→ Controlled Revision
```

用户感知到的三项优势：
1. 更懂我要表达什么。
2. 更会组织读者体验。
3. 修改时不乱动已经好的地方。

## Product Philosophy

- AI proposes, user accepts.
- 成功段落是资产，不应因为一次 Revision 被随意重写。
- 写作不仅是 generation，还包括 structure / inspection / revision / versioning。
- Beginner 只需 Material + Intent + Generate。
- Advanced 用户才展开 Reader Experience / Locks / Writing Map。

## V0 Success

用户能完成：

```text
Add Material
→ Set Intent
→ Generate
→ Select Weak Passage
→ Patch
→ Compare
→ Accept/Reject
→ Restore Version
```
