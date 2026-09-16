# 任务与项目删除规格

状态：已实现并通过自动验收。日期：2026-09-14（任务删除），2026-09-15（项目删除）。

本规格响应用户对“不想要的任务和项目删除掉”的明确需求，扩展 Product V0 的 Task/Project 管理界面。它只规定删除，不改变 Draft、Version、Idea 或 Source 的日常语义。

## 用户结果（任务）

- 首页最近任务、全部任务、项目任务区均提供“删除”。
- 工作台“信息”页也可删除当前任务。
- 删除前必须显示任务名、清理范围和不可恢复提示；用户取消时不产生写入。
- 成功后任务立即离开列表；从工作台删除时返回全部任务页。
- 运行中的任务返回冲突提示，等待运行结束后才允许删除。

## 用户结果（项目）

- 首页项目区、项目列表页和项目详情页均提供“删除”。
- 删除前必须显示项目名、清理范围（全部任务、正文、版本、检查、运行记录和素材）和不可恢复提示；用户取消时不产生写入。
- 成功后项目立即离开列表；从项目详情页删除后返回项目列表页。
- 项目中存在运行中任务时返回冲突提示，等待运行结束后才允许删除。

## 数据契约（任务）

接口：`DELETE /tasks/{task_id}`。

成功返回：

```json
{
  "id": "task_...",
  "deleted": true,
  "returned_ideas": 0,
  "removed_unlinked_sources": 0
}
```

删除必须在一个 SQLite 写事务内完成：

1. 拒绝存在 `running` operation 的任务，返回 `409 TASK_RUNNING`；
2. 保留关联 Idea，解除 `task_id`；`written` 状态回到 `to_write`，`archived` 保持归档；
3. 删除任务的 Draft、Version、Patch、Review、修订工作单、保留原文、依据检查、读者路径、Meaning、Plan、Generation Result、Operation/Event/Record、配置和 Source 关联；
4. 删除 Task；
5. Project 下的 Source 作为素材库内容保留；无 Project 且已无任何 Task 引用的 Source 一并清理；
6. 若任一步失败，整项删除回滚，不允许留下半删除状态或跨表断链。

未知任务返回 `404 NOT_FOUND`。删除接口不负责停止或取消模型调用。

## 数据契约（项目）

接口：`DELETE /projects/{project_id}`。

成功返回：

```json
{
  "id": "proj_...",
  "deleted": true,
  "deleted_tasks": 1,
  "returned_ideas": 0,
  "removed_sources": 2
}
```

删除必须在一个 SQLite 写事务内完成：

1. 拒绝存在任意 `running` operation 的项目内任务，返回 `409 TASK_RUNNING`；
2. 对项目内每个任务执行任务的完整删除（Idea 解除并回到待写、Draft/Version/Patch/Review/修订工作单/依据/读者路径/Meaning/Plan/Generation/Operation 等全部清理）；
3. 删除指向本项目素材的 `task_sources` 链接（含其他项目任务对本项目素材的引用），再删除本项目全部 Source；
4. 删除 Project；
5. 若任一步失败，整项删除回滚，不允许留下半删除状态或跨表断链。

未知项目返回 `404 NOT_FOUND`。删除接口不负责停止或取消模型调用。

## 交互与并发

- 列表删除不需要先打开任务。
- 工作台删除前先等待当前自动保存结束，避免保存请求与删除请求竞速。
- 确认期间按钮不可触发重复删除；请求期间禁用当前删除按钮。
- 后端是最终并发边界。即使列表显示任务空闲，只要删除事务发现运行记录仍为 `running`，就拒绝删除。

## 验收

1. 取消确认后任务和数据保持不变。
2. 成功删除后 GET Task 为 404，所有任务入口不再显示该任务。
3. 正文、版本、检查、提案及 operation 子记录均无孤儿行。
4. Project Source 保留；独立任务的无主 Source 被清理。
5. 关联 Idea 回到待写，可再次创建任务。
6. 运行中删除返回 409，Task 与配置仍完整。
7. 备份严格关系校验仍通过。
8. 成功删除项目后 GET Project 为 404，项目内任务、正文、版本、检查、素材及跨表 task_sources 链接均无孤儿行。
9. 引用本项目素材的其他项目任务在项目删除后仍可访问，指向被删素材的 task_sources 链接已被清理。
10. 项目中存在运行中任务时删除返回 409，项目与任务保持完整。

## 素材编辑与删除（2026-09-15）

工作台“素材”面板与项目详情页“素材”列表均提供“修改”和“删除/移除”。

### 工作台素材（任务内）

- 修改：`PATCH /tasks/{task_id}/sources/{source_id}`，`{title?, content?}`。
  - 仅当该素材只被当前任务引用（task_sources 计数为 1）时才就地修改；否则返回 `409 SHARED_SOURCE`，提示在项目页修改或先解除其他引用。
  - 修改后失效该任务的修订上下文（revision_items/preserved_spans 标记 stale），下次生成与检查使用新素材。引用该素材的依据卡因 sources 快照变化而自动 stale。
- 移除：`DELETE /tasks/{task_id}/sources/{source_id}`。
  - 删除该任务对该素材的 task_sources 链接；若素材无项目归属且无其他任务引用，一并删除素材行。
  - 删除该素材在本任务草稿上的 claim_links（断开依据卡对该素材的引用），并把引用这些 claim_link 的 proposed_patches.claim_link_id 置空（保留 Before/After 提案）。
  - 失效该任务的修订上下文。项目库素材仅解除引用，不删除素材行。

### 项目库素材

- 修改：`PATCH /sources/{source_id}`，`{title?, content?}`。就地修改素材，影响所有引用它的任务；逐个失效受影响任务的修订上下文。素材仍被引用，claim_links.source 关系不变，依据卡按快照失效。
- 删除：`DELETE /sources/{source_id}`。
  - 删除素材行、所有 task_sources 链接、引用该素材的全部 claim_links；把引用这些 claim_link 的 proposed_patches.claim_link_id 置空。
  - 逐个失效受影响任务的修订上下文。
- 未找到素材返回 `404 NOT_FOUND`。

### 验收（素材）

11. 工作台修改独占素材后内容更新、依据卡 stale、备份通过；共享素材修改返回 409 且不影响其他任务。
12. 工作台移除素材后 task_sources 与对应 claim_links 清空，无主素材行删除，备份通过；项目库素材仅解除引用、素材行保留。
13. 项目库删除后素材行、所有 task_sources 与 claim_links 清空，引用其 claim_link 的 proposed_patches.claim_link_id 为空，备份通过。
14. 项目库修改后所有引用任务看到新内容并失效修订上下文，备份通过。
