# Narrative Writing Workbench V0.2 — Export and Backup

本目录是 Product V0 的增量规格，只增加本地导出、工作区备份和安全恢复。它不替换 V0/V0.1，不改变写作引擎、WIR、检查或补丁语义。

实现顺序：

1. 当前工作副本与指定 Version 的 Markdown/纯文本导出；
2. 全工作区一致性备份、预检和恢复到独立工作区；
3. 完成自动化与人工验收后再决定是否增加 DOCX/PDF 或项目级子集备份。

权威文件：

1. [EXPORT_BACKUP_IMPLEMENTATION_TASK.md](EXPORT_BACKUP_IMPLEMENTATION_TASK.md)
2. [product/21_EXPORT_AND_BACKUP.md](product/21_EXPORT_AND_BACKUP.md)
3. [product/22_API_AND_PACKAGE_CONTRACT.md](product/22_API_AND_PACKAGE_CONTRACT.md)
4. [product/23_ACCEPTANCE_CRITERIA.md](product/23_ACCEPTANCE_CRITERIA.md)

发生冲突时，V0 规格继续决定既有产品行为，本扩展只决定导出与备份功能。本地导出不是“Publishing integration”；不向外部服务上传或发布内容。
