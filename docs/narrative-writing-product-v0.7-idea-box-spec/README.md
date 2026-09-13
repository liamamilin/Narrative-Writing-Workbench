# Product V0.7 本地选题箱

本规格扩展 Product V0/V0.1，在 Quick Write 中把用户明确收藏的选题持久化到本地工作区。

```text
Generate suggestions (session only)
→ Save an idea
→ Add note / status
→ Start or reopen its writing task
```

核心规则：

- 新生成但未收藏的话题不是长期用户数据；页面明确区分“本次生成”和“选题箱”。
- 收藏后的选题保存在 SQLite，进入 F01 工作区备份。
- 旧 `qw_topic_lib_v1` 迁移必须幂等；服务端完整确认前不删除浏览器副本。
- 只按明确的 Unicode/空白/大小写标准化相等去重，不把语义相似话题自动合并。
- 选题与 Task 关联后可打开原任务；创建关联任务仍使用现有 Quick Write 安全流程。

实现前先读 Product V0 与 V0.1，再读本目录实施任务和 `product/36..38`。
