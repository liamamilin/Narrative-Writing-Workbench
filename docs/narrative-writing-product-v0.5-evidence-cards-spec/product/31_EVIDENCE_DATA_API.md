# Evidence Data and API

## Engine Output

adapter 返回结构化 `claims`，每项包括：

```text
id
claim_type = fact | author_inference | value_judgment
draft_quote
paragraph_start / paragraph_end
relation = supported | inference | insufficient | conflict
explanation
source_id?
source_quote?
revision_goal
```

服务端校验 Draft 引文、段落范围、Source ID 归属和 Source 引文。无可靠材料锚点的 `supported` 或 `conflict` 必须降为 `insufficient`；无材料锚点的 `inference` 可以保留，但不能显示材料支持。

## Persistence

`claim_checks` 保存 task/draft、Draft revision/hash、Source 集合与逐份内容 hash、operation 和创建时间。

`claim_links` 保存正文精确字符区间与 quote、可选 Source 精确字符区间与 quote、关系、陈述类型、说明、修订目标、用户状态和可选 patch 关联。

用户状态：`unreviewed / confirmed / dismissed`。关系和用户状态是独立字段。

## API

```http
POST /tasks/{task_id}/check-evidence
GET  /tasks/{task_id}/evidence-check
POST /claim-links/{link_id}/confirm
POST /claim-links/{link_id}/dismiss
```

`POST /tasks/{task_id}/patch` 可带 `claim_link_id`。服务端核验该卡属于当前 Task、检查未过期且状态可处理，并强制使用卡片锚定的正文范围。

错误必须使用现有产品级 error shape。输入超限、任务不适用、结果过期和引文校验失败应具有不同 code。
