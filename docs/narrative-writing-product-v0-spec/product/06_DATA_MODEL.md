# Data Model

数据库技术不限，但语义对象必须保持一致。

## Project

```text
id
name
description
created_at
updated_at
```

## Source

```text
id
project_id?
title
type
content
metadata_json
created_at
updated_at
```

type：
- pasted_text
- uploaded_file
- note

## Task

```text
id
project_id?
type
title
instruction
status
expected_language
created_at
updated_at
```

status：
- draft
- generating
- ready
- failed
- done

## TaskSource

```text
task_id
source_id
role
```

role 可为 primary/context/reference。

## WritingConfig

```text
task_id
immersion
explicitness
intensity
target_length
locks_json
constraints_json
```

## EnginePlan

内部对象：

```text
id
task_id
schema_version
data_json
created_at
```

raw data_json 不直接给普通 UI。

## Draft

```text
id
task_id
current_version_id
working_content
updated_at
```

working_content 用于 autosave 的未 checkpoint 内容。

## Version

```text
id
draft_id
parent_version_id?
content
source_type
instruction?
created_at
```

source_type：
- generation
- patch
- manual_checkpoint
- restore

内部可形成 version graph；V0 UI 可暂时线性展示。

## ProposedPatch

```text
id
draft_id
base_version_id
selection_json
instruction
before_text
after_text
status
created_at
```

status：
- proposed
- accepted
- rejected

关键 invariant：

```text
ProposedPatch != Version
```

Accept 后才创建 Version。

## Review

```text
id
draft_id
version_id
summary_json
issues_json
created_at
```

## Invariants

1. 一个 Task 最多一个 active Draft。
2. current_version 必须属于该 Draft。
3. Rejected patch 不得修改 current content。
4. Restore 必须可逆。
5. Locks 必须持久化并可追溯。
6. EnginePlan 必须能追溯到生成它的 task/config。
