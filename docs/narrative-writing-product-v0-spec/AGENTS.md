# AGENTS.md

Specification-first project.

Coding Agent rules：

1. 先读 `PRODUCT_IMPLEMENTATION_TASK.md`。
2. 按编号读 Product Spec。
3. 不要未经说明重新设计产品。
4. 保持实现简单。
5. Engine internals 必须在 adapter 后面。
6. 普通用户界面不要出现 WIR/Critic/Patcher。
7. Patch/Version safety 是硬约束。
8. 不做 V0 scope 之外的功能。
9. 编码前创建 `../reports/PRODUCT_IMPLEMENTATION_REVIEW.md`。
10. 完成后创建 `../reports/PRODUCT_V0_IMPLEMENTATION_REPORT.md`。

冲突处理：
- 报告冲突
- 优先更具体、更 normative 的文档
- 采用最小兼容解释
- 记录决定

Priority：

```text
Golden Path
> Revision Safety
> Version Safety
> Product Polish
> Extra Features
```
