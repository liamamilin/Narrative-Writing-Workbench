# V0.1 稳定性实现契约

日期：2026-09-13。适用本轮产品层实现；规范依据及冲突决定见 [实施评审](../reports/PRODUCT_IMPLEMENTATION_REVIEW.md)。引擎 WIR 语义不变。

## 正文写入

Draft 增加整数 `revision`。手工正文发生变化和创建新 Version 时单调递增；相同正文的 autosave 和去重 checkpoint 不递增。提交前保存尚未 checkpoint 的工作副本时，可能一次返回跨过两个 revision，客户端应直接采用服务端返回值。

| 请求 | 输入 / 规则 | 成功返回 |
|---|---|---|
| `PATCH /drafts/:id` | `working_content`、`expected_revision` | 新 revision |
| `POST /tasks/:id/checkpoint` | `expected_revision` | version_id、revision、可选 deduped |
| `POST /versions/:id/restore` | `expected_revision` | 新 version_id、revision |
| `POST /tasks/:id/generate`、regenerate、rediscover-angle | 已有稿件时须带 `expected_revision` | version_id、revision、operation_id |
| `POST /tasks/:id/patch` | `expected_revision`、selection、instruction；可选 base_version_id、review_id | 提案，正文不变 |
| `POST /patches/:id/accept` | 使用提案保存的 base_revision；不接受调用方放宽冲突 | 接受后版本与新 revision |

缺失、负数、布尔值、字符串 revision 返回 `REVISION_REQUIRED` / HTTP 428；过期 revision 返回 `STALE_BASE` / HTTP 409。先重载、核对正文再操作，不能盲目用新 revision 重发旧正文。前端冲突副本存于当前标签页 sessionStorage，并支持下载后重载；关闭标签页前应下载重要的未保存输入。

补丁接受与拒绝、接受与接受的竞争只有一个终态。重复解决同一提案仍返回 `STALE_PATCH` / 409；接受关联保存在 `accepted_version_id`。锁约束与选区校验在同一提交事务中执行。网络模型调用在事务外进行。

## 版本与诊断来源

- Version 增加 `engine_plan_id` 与 `restore_source_version_id`。parent 指向操作前的当前版本，restore source 指向恢复内容的来源。
- 初次生成记录实际使用的 plan；接受补丁和手工 checkpoint 继承原 plan；Restore 继承被恢复版本的 plan。
- 历史不可证实的 plan 保持 NULL；不通过“任务最新 plan”猜测。人工修改后的地图只作生成结构参考，段落对应仍为启发式。
- Review 保存内容 hash、revision、目标/素材/配置快照；当前文本或目标改变后 `stale=true`。由旧诊断发起提案返回 `STALE_REVIEW` / 409。
- 生成成功但提交冲突时，生成正文仍保存到 generation_results，并通过 operation detail 的 `unapplied_result` 返回，供复制核对。

## 旧稿入口

`draft_revision` 必须有非空 material。创建任务在一个事务内保存原稿、Draft 和 `manual_checkpoint` 初始版本，instruction 为“导入原稿”；不生成 EnginePlan。默认进入检查页，随后使用提案与接受流程。该模式的 Generate 返回 `DRAFT_REVISION` / 409，避免把导入旧稿当素材重写全文。

升级旧库时，仅对“没有任何 Draft、恰好一个非空 primary Source”的旧稿任务恢复原稿版本，已有稿件不会被替换。来源不明确的历史任务不自动猜测。

## 有界运行与重连

每个 generate / regenerate / rediscover-angle / review 创建新的 writing_operations 记录。数据库唯一索引保证同一任务最多一个 running 操作；第二个请求返回 `GENERATING` 或 `REVIEWING` / 409。时间长不等于进程已死，不按五分钟阈值释放占用。

状态：`running → succeeded | failed | interrupted`。运行保存进程编号、阶段、时间、输入指纹、模型角色配置和提示词 hash、错误码及结果关联。endpoint 仅保存 hash，API Key 不进入快照；未取得 usage 时保留 NULL。

- `GET /tasks/:id` 返回最新 `operation` 的产品安全状态。
- `GET /tasks/:id/operations/:operation_id` 返回状态、阶段事件、结果 ID、未应用的生成正文、产品安全的阶段/模型调用记录及 usage 汇总，不暴露 plan、提示词、输入正文、模型输出或原始推理。
- `GET /tasks/:id/progress?operation_id=...` 只回放并跟随这一运行；SSE 事件带 operation_id 与 seq。
- `after_operation_id=...` 用于先订阅再提交的短暂等待，避免误重放上次运行。逐 token 预览仅保留在内存，重启后可查看持久阶段及最终状态。
- 前端通过运行状态轮询辅助 EventSource；连接断开不自动触发新的生成。进程重启将旧 running 标记为 interrupted，用户手动重试。
- 运行使用开始时的 engine adapter；更换设置对后续运行生效。意义/结构续跑必须匹配对应输入与模型/提示词指纹。

每次模型调用仅记录产品阶段名、文本/结构化调用类型、状态、模型名、耗时和提供方实际返回的 token usage。流式或兼容端点没有返回 usage 时记录为 NULL，并在汇总中增加 `unknown_calls`、令 `complete=false`，不能将未知成本记作零。意义发现的每次尝试、命题评审结论、结构生成/复用、语言检查、输出门和审阅决策作为 `stage_result` 记录；补丁提案也拥有独立 operation。记录只写本地数据库。

当前支持一个本机服务进程。通过 `python -m workbench.server` 启动时获得数据库旁的 OS 文件锁；不得绕过入口用多个 uvicorn workers 共享库。直接嵌入 create_app 的调用方同样须满足单进程约束。

## 数据迁移与回退

当前 `PRAGMA user_version=3`。数据库打开时执行幂等增量迁移；DDL 与数据回填处于同一事务。检测到未来版本号时拒绝打开，防止旧代码意外降级库。

已有库升级前自动使用 SQLite backup API 保存到 `<database>.pre-v3-<唯一编号>.sqlite3`。这是一致性备份，包含 WAL 中的已提交内容。文件包含本地写作数据，已加入忽略规则。新库不需要升级备份。

回退时先停止服务，保全升级后的完整数据，再使用 SQLite backup 从备份恢复到**另一条路径**；用旧版本连接该路径验证对象数、正文及版本链。不能将旧代码直接指向未经确认兼容的新库。本轮仅在临时数据库演练，未对用户库执行升级。
