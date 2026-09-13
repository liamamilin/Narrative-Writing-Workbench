# Evidence Cards Acceptance

## Required

1. 只有适用的 source-grounded 非虚构任务显示检查入口。
2. 检查只接收 Task 显式关联的 Source，超限明确拒绝。
3. 每张可操作卡的正文 quote 与字符区间能逐字对应当前 Draft。
4. `supported` 和 `conflict` 的 Source ID、quote 与字符区间能逐字对应对应 Source。
5. 非法 Source、错误引文和重复 ID 不进入可信结果。
6. 关系与用户状态分开显示和保存。
7. 用户可从卡片定位正文和查看材料原句。
8. 正文或 Source 变化后结果过期，旧卡不能继续操作。
9. “处理”生成局部 ProposedPatch；Accept 前正文不变，Reject 不改正文。
10. 备份严格校验 v5，并能恢复 v3/v4 后增量升级。

## Evaluation Fixtures

至少覆盖：真实支持、部分支持/推断、相反材料、无关材料、数字错配和价值判断。自动化验证契约与安全属性；模型误报、漏报和用户核查耗时留待真实引擎样本评估。
