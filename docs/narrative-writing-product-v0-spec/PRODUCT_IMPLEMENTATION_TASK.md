# PRODUCT_IMPLEMENTATION_TASK

## Objective

实现 Narrative Writing Workbench 的 Desktop Web V0。

不要重新设计产品，不要做成 chatbot。

Engine 已由 Narrative Writing Harness 提供；本任务实现 Product Layer。

## Read First

1. README.md
2. product/00_PRODUCT_VISION.md
3. product/01_PERSONAS_AND_JTBD.md
4. product/02_INFORMATION_ARCHITECTURE.md
5. product/03_USER_FLOW.md
6. product/04_SCREEN_SPEC.md
7. product/05_INTERACTION_SPEC.md
8. product/06_DATA_MODEL.md
9. product/07_API_CONTRACT.md
10. product/08_PRODUCT_COPY.md
11. product/09_V0_SCOPE.md
12. product/10_ACCEPTANCE_CRITERIA.md

编码前创建：

`../reports/PRODUCT_IMPLEMENTATION_REVIEW.md`

内容必须包括：
- Product understanding
- proposed stack
- file structure
- screen → route/component mapping
- product API → engine adapter mapping
- persistence
- state management
- test plan
- milestones
- ambiguities

## Core User Journey

```text
Material
→ Intent
→ Generate
→ Read
→ Review
→ Patch
→ Accept
```

## Recommended Technical Direction

优先简单 Desktop Web stack，例如：

```text
Next.js / React
+
FastAPI (or equivalent)
+
SQLite
```

若现有 repo 有明显更合适的简单栈，可采用等价实现。

禁止过度工程化：
- microservices
- complex event bus
- heavy agent framework UI

## Required Screens

1. Home
2. New Task
3. Writing Workspace
4. Writing Map
5. Version History / Compare
6. Project

## Workspace

Desktop 三栏：

```text
Sources | Draft | Writing Panel
```

Writing Panel：

```text
Goal | Review | Locks | Settings
```

## Required Interactions

### Generate
Material + Intent → Draft

### Review
Issue → Show / Fix

### Patch
Selection → instruction → proposed patch → before/after → accept/reject/retry

### Version
Accepted patch creates version.

### Writing Map
Read-only V0.

## Engine Adapter

产品组件不得直接依赖具体 agent 实现。

提供统一接口，例如：

```text
generate()
review()
patch()
get_writing_map()
```

允许：

```text
MockWritingEngine
RealWritingEngine
```

但 mock 和 real 必须接口一致。

## Persistence

需要持久化：
- Project
- Source
- Task
- WritingConfig
- Draft
- Version
- ProposedPatch
- Review

## Hard Revision Rule

```text
AI proposes, user accepts.
```

Patch 在 Accept 前绝不能静默修改当前 Draft。

## Milestones

M0 Product Review  
M1 App Skeleton  
M2 Home + New Task  
M3 Workspace  
M4 Generation  
M5 Local Patch  
M6 Version History/Compare  
M7 Review  
M8 Writing Map  
M9 Project  
M10 Tests + Acceptance

## Required Tests

至少：
- project/source/task creation
- generation success
- generation failure safety
- autosave
- patch proposal
- patch accept/reject
- version creation/restore
- locks
- writing map
- issue show/fix
- project → task flow

## Completion

创建：

`../reports/PRODUCT_V0_IMPLEMENTATION_REPORT.md`

报告：
- stack
- routes
- components
- data model
- engine adapter
- tests/results
- limitations
- deviations
- recommended next milestone

## Stopping Rule

满足 `product/10_ACCEPTANCE_CRITERIA.md` 后停止。

不要自动进入 V0.5 / V1。
