# Idea Box Flow

## Suggestions and Saved Ideas

话题建议仍由用户主动触发。响应先放在当前 Quick Write 页面中的“本次生成”，刷新后可以消失；每张候选提供“收藏”。用户手工输入的话题也可明确收藏。

收藏进入“选题箱”，保存话题、hook、领域、备注、状态和来源。状态限定为：

- `to_write`：待写；
- `written`：已关联写作任务；
- `archived`：归档。

## Continue Writing

未关联 Task 的条目可以填入 Quick Write 表单。用户开始写或确认角度创建 Task 时，Idea 与 Task 在同一事务关联并变为 `written`。已关联条目显示“打开文章”，不重复创建任务。

## Legacy Migration

进入 Quick Write 时读取 `qw_topic_lib_v1`。最多 200 条一次提交给迁移 API；服务端按标准化话题幂等写入并返回 received/imported/existing。只有 `imported + existing == received` 时客户端删除旧 key。网络、校验或服务端失败时原 key 保留，并提示可重试。
