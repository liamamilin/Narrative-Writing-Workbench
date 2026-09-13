# Product V0.5 论点与素材依据卡

本规格是 Product V0 的增量规格，只适用于用户已提供素材的非虚构写作任务。

目标流程：

```text
Current Draft
→ Check Evidence
→ Claim Card
→ Inspect Draft Quote + Source Quote
→ Confirm / Mark for Follow-up
→ Propose Local Revision
```

核心规则：

- 只检查当前 Task 显式关联的 Source，不联网补证据。
- 精确引文存在不等于陈述真实；用户确认关联也不等于外部事实认证。
- `supported / inference / insufficient / conflict` 描述材料关系，`unreviewed / confirmed / dismissed` 描述用户动作，两者不得混用。
- 正文或素材发生变化后，旧检查结果必须明确过期。
- 引文、Source ID 或范围不能确定性核验时，不得显示“材料支持”。
- 修订继续使用 ProposedPatch；AI 只提出，用户决定是否接受。

实现前依次阅读 Product V0，再读本目录的实施任务与 `product/30..32`。
