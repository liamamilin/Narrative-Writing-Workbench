# Information Architecture

## First-Class User Objects

V0 只暴露：

```text
Project
Source
Task
Draft
Version / Revision
```

不把这些作为一级用户对象：

```text
Architect
WIR
Reader State
Beat
Critic
Patcher
```

## App Structure

```text
App
├── Home
├── Projects
│   └── Project
│       ├── Sources
│       ├── Tasks
│       └── Drafts
├── Writing Workspace
├── Writing Map
├── Version Compare
└── Settings
```

## Recommended Routes

```text
/
 /projects
 /projects/:projectId
 /tasks/new
 /tasks/:taskId
 /tasks/:taskId/map
 /tasks/:taskId/versions
 /tasks/:taskId/versions/compare
 /settings
```

## Project

作用仅为：

```text
Context Container + Work Organization
```

V0 不做 Knowledge Graph / Timeline Engine / Agent Memory UI。

## Task

一次具体写作任务，拥有：
- type
- instruction
- config
- relevant sources
- engine plan
- draft
- versions

## Draft

当前被用户接受的正文，不是 Chat History。

## Revision

必须区分：

```text
Proposed Patch
Accepted Version
```

AI patch 在用户 Accept 前不得变成当前版本。

## Workspace

预计用户绝大多数时间停留在 Workspace，因此：
- Draft editor 占最大空间
- Project management 保持轻量
- generation controls 从属于正文
