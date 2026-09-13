# 23 — Acceptance Criteria

## 文本导出

- 当前稿导出前保存编辑器最新内容，并用保存后的 revision 请求。
- 保存失败、缺失 revision 或并发改稿时不返回 200 下载。
- `include_title=false` 时，md/txt 响应字节解码后与所选正文完全相同。
- `include_title=true` 只增加约定标题，不改变正文。
- 中文、连续空行、尾部换行、表情、`#_*[]` 等 Markdown 字符不丢失。
- 任意 Version 可导出；随后修改当前稿不会改变该 Version 的导出。
- 导出不增加 Version，不改变 Draft revision，不运行模型。
- 响应文件名不允许换行、路径分隔符或 header 注入。
- UI 能从工作台导出当前稿，并从版本页导出指定版本。

## 备份与恢复

- 活跃 SQLite 在 WAL/并发读取条件下得到一致性快照。
- manifest hash、大小、对象数与快照一致，且不包含密钥/settings/env。
- 缺文件、多文件、坏 zip、hash 错误、超限、路径越界、SQLite 损坏和未来 schema 被拒绝。
- 预检及失败恢复不改变当前库，也不留下半成品目标。
- 成功恢复到新位置后，关键表对象数、引用关系、当前正文和版本内容与备份一致。

## 当前阶段声明

E0–E2 通过后可声明“Markdown/纯文本导出完成”。只有 E3–E6 全部通过后才能声明“本地备份与恢复完成”。
