# Product V0.6 读者路径检查实施评审

日期：2026-09-13。依据 Product V0、[V0.6 增量规格](../narrative-writing-product-v0.6-reader-path-spec/README.md)与 F05 规划。

## 现状与决定

现有 Writing Map 显示生成时计划，并用启发式把 beat 映射到段落；它不能说明手工修改后的实际成稿。现有 Review 有总体维度和局部问题，但没有完整逐段作用、认识增量和问题回答链。

实现将在产品 adapter 增加 `review_reader_path()`，使用独立外置 prompt/schema。数据库不复制第二套问题状态：`reviews` 增加 `analysis_type`，路径问题直接写入 F03 `revision_items`；`reader_path_steps` 只保存逐段只读产物。普通 Review 查询明确筛选 writing 类型，避免两类检查相互覆盖。

## 数据与安全

路径步骤要求覆盖每个非空段落一次，完整 paragraph quote 逐字相等；缺失、重复或越界使整轮失败。问题 quote 在声明范围内必须唯一定位，否则不创建工作单。Draft revision/hash 变化即过期，提案和接受沿用 F03 的二次校验与事务。

数据库升为 v6，备份为 v3–v6 分版本严格契约。输入上限为 30,000 字符、80 个非空段落、单段 10,000 字符。

## 界面与验证

中心视图增加“稿件检查”，与“原定路径”并列。逐段卡可定位正文；问题可定位、处理或跳过。专项测试覆盖离线样例、完整覆盖、Unicode/空段、错误引用、过期、Patch 状态、Review 隔离、迁移/备份和并发。浏览器 B16 走通检查、导航、拒绝/重开、接受/过期。
