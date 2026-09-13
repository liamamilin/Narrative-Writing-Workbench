# Evidence Card Flow

## Availability

入口只在以下条件同时成立时可用：

- Task 的 `input_mode` 为 `source_grounded`；
- Task 类型为 `narrative_analysis`、`character_analysis` 或 `essay`；
- 已有当前 Draft；
- 至少关联一个非空 Source。

小说、情感重述、自由写作和 topic-only 不套用事实依据检查。没有材料时提示添加 Source。

## Check

用户点击“检查材料依据”后，系统把当前正文及显式关联的材料快照交给 adapter。第一版限制为：正文最多 20,000 字符、最多 20 个 Source、材料总计最多 60,000 字符。超过限制返回可操作错误，要求用户缩小材料范围。

每轮最多返回 12 张关键陈述卡。系统应优先检查可核查的具体陈述，包括数字、事件、归因、因果或明确概括；不强行把纯价值判断伪装成事实核验。

## Inspect and Act

卡片显示：

- 正文原句及段落位置；
- 材料关系；
- 判断说明与限定条件；
- Source 名称与材料原句（如有可靠关联）；
- “定位正文”“查看素材”“确认关联”“本轮忽略”“处理”操作。

“处理”只提供三类局部目标：删去无依据陈述、改写为明确推断、补入材料中的限制条件。它生成 ProposedPatch，正文在 Accept 前不变。

## Staleness

正文修改、生成、恢复、接受 Patch，或关联 Source 新增/修改后，当前检查整体过期。过期结果仍可查看，但不能确认、忽略或发起修订；用户必须重新检查。
