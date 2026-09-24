# Product V0.8 文章分享

本规格扩展 Product V0–V0.7，为已经保存的正文增加可撤销的公开阅读快照。

```text
Current saved draft
→ Create immutable share snapshot
→ Copy link / save share card
→ Open focused public reading page
→ Revoke when no longer needed
```

核心规则：

- 分享入口属于当前文章，位于正文工具栏的“版本”之后。
- 分享的是创建时的正文快照；后续编辑不会静默改变已分享内容。
- 公开页面只包含标题、正文、可选署名、摘要和发布时间。
- 素材、写作目标、检查、保护项、版本历史、模型信息、operation 和 API Key 永不进入公开响应。
- 链接使用不可猜测的 bearer token，默认 `noindex,nofollow`，可以随时停止分享。
- 删除 Task 或 Project 时同步删除其分享快照，旧链接立即失效。
- 本功能不增加账户、协作、评论、关注、推荐流或第三方发布平台集成。

Product V0 将 publishing integration 列为范围外；本目录是用户明确要求后的窄范围扩展，只开放文章快照和阅读页面，不改变 V0 的其他边界。

实现前先读 Product V0，再读本目录实施任务与 `product/39..41`。
