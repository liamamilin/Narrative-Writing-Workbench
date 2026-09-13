# Idea Box Data and API

## Data

`ideas`：

```text
id, topic, normalized_topic, hook,
domain, domain_name, note,
origin, source_key, status, task_id,
created_at, updated_at
```

`normalized_topic` 使用 Unicode NFKC、连续空白折叠、trim 和 casefold。它具有唯一约束；语义相似但标准化后不相等的条目分别保留。`source_key` 记录导入/生成来源，不保存账户或密钥。

## Limits

- topic：1–500 字符；
- hook：最多 500；note：最多 2,000；
- domain/domain_name：各最多 120；
- 单次 legacy import：最多 200 条；
- 列表 limit：1–200，默认 100。

## API

```http
GET   /ideas?q=&status=to_write|written|archived|all&limit=100
POST  /ideas
PATCH /ideas/{idea_id}
POST  /ideas/import-legacy
```

创建返回 `idea` 与 `created`；标准化重复返回既有条目。更新只允许 note/status。Idea 与 Task 的关联通过现有 `POST /tasks` 的可选 `idea_id` 完成：只允许 topic-only、话题必须标准化相等、未关联条目才能绑定；任务和关联必须在同一事务提交。
