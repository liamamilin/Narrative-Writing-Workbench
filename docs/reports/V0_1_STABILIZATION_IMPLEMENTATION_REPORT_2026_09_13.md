# V0.1 首轮稳定性开发报告

日期：2026-09-13。开发基线：main / `72304ad`。实现位于 `codex/v0-1-stabilization` 并已推送到 GitHub；无关 `.commandcode/` 文件保留在本地且未提交。

## 交付结论

核心写入安全、版本来源、运行恢复、操作观测和设置反馈已实现，并通过本地回归。浏览器实际发现并修复了旧稿入口未建立 Draft、恢复版本后的异步页面覆盖和中断后重试入口三个额外问题。固定真实模型 12 例工程评估已完成；原生输入法人工走查和人工质量评分尚未完成，因此不能宣称整份 S00–S08 计划或产品质量评估已经完成。

进展持续记录在 [DEVELOPMENT_PROGRESS.md](DEVELOPMENT_PROGRESS.md)，具体数据/API 变化见 [稳定性实现契约](../planning/STABILIZATION_API_AND_DATA.md)。

## 完成的实现

| 范围 | 修改后的行为 | 主要文件 |
|---|---|---|
| 提交安全 | 接受/拒绝和版本更新使用同一事务；任一步失败整体回滚；重复接受只增加一个版本 | workbench/db.py、service.py |
| revision | autosave、checkpoint、restore、生成及提案比较正文 revision；迟到写入不能覆盖更新后的稿件 | service.py、api.py、static/app.js |
| 本地恢复 | 冲突时保留输入，刷新后仍可查看当前标签页的恢复副本；可下载后载入服务端稿件 | static/app.js |
| 来源一致性 | 版本记录实际 plan；恢复 A 后解释与结构回到 A；未知来源保持 NULL | db.py、service.py |
| 审阅安全 | review 绑定内容、revision、目标和素材配置；过期诊断不能直接修改新稿；保护项变化使旧提案失效 | service.py、static/app.js |
| 长任务 | 持久运行编号、原子占用、阶段/调用记录、适配器快照、输入指纹与有条件续跑；超过五分钟不允许重复启动 | operations.py、service.py |
| 断线/重启 | SSE 绑定 operation_id；轮询帮助重连；启动标记旧进程操作中断，不自动调用模型 | api.py、progress.py、server.py、instance.py |
| 设置反馈 | 模型清单只给建议；失败保留手填值；忽略过期响应；审阅仅展示白名单质量项 | static/app.js |
| 旧稿入口 | 原稿直接建立 Draft/初始手工版本，默认进入检查；不要求先全文生成；旧库可证明来源时恢复原稿 | service.py、db.py、static/app.js |
| 操作观测 | 记录意义尝试、评审结论、结构、语言/输出检查、补丁和模型调用耗时；usage 不可得时明确未知；不保存输入输出 | operations.py、engine/real.py、llm_client.py |
| 迁移 | schema v3，增量迁移处于事务中；升级前 SQLite 一致性备份；失败回滚；未来 schema 拒绝降级打开 | db.py |
| 测试交付 | 合成 fixture、源码隔离测试入口、独立 mock 服务、浏览器套件、CI 和有界评估脚本 | tests/、scripts/、.github/ |

引擎编排语义与提示词未改动；`app/llm_client.py` 仅增加与产品 operation 绑定的提供方元数据观察钩子。未引入新编排框架，也未开始 F01–F09 候选新功能。

## 验证记录

- 初始基线：270 项；第一次源码隔离执行暴露 fixture 的 Path 导入缺失，已修正。
- 最终完整源码隔离：298 passed / 27.36 秒；包括锁变化、配置原子性、调用元数据安全、失败模型定位和未知 usage 回归，JS 语法检查通过。
- 浏览器：B01–B10 共 10 个场景通过，未捕获未处理页面异常。工具为 Playwright 1.62.1 与独立 Chrome；没有使用个人浏览器资料。
- 真实页面缺陷经过“失败截图 → 修复 → 重跑”闭环：B03 旧稿只存素材；B05 恢复后旧版本页异步返回覆盖新路由。
- B06 验证双标签页冲突、阻止丢输入的导航、刷新后恢复副本及下载重载；B07 在生成中 SIGKILL mock 服务，再用同一端口和数据库重启，验证旧操作中断、页面提示和用户手动重试成功。
- B09 自动检查 5,200 字中文剪贴板粘贴、保存后刷新、合成 composition、反向 Shift 连续选择、跨段 DOM 文字选择及 ¶2–3 提案范围；B10 已查看 1280×800 工作台与 1440×1000 快速写作截图，并验证 Writing Map Enter、话题卡 Enter/Space、Escape 关闭对话框和焦点恢复。没有把自动化剪贴板或合成事件当作原生输入法实测。
- 三种入口各 4 个合成案例：12/12 完成 mock 演练，共导出 24 个 operation 的事件、阶段/调用记录、耗时和 usage。旧稿案例检查提案不自动应用、接受只改指定段落。人工评分为空；mock adapter 不经过提供方，24 个 usage 均明确为未知。
- 固定 `gpt-oss:120b-cloud`、单次 120 秒和零重试的真实评估：12/12 案例完成，24/24 operation 与 40/40 模型调用成功；累计 151.71 秒。32 次非流式调用报告 83,923 input / 30,085 output tokens，8 次流式正文调用 usage 未返回。质量结论等待人工评分，详见 [真实模型评估报告](REAL_MODEL_EVALUATION_REPORT_2026_09_13.md)。
- 迁移在临时旧库验证幂等、原稿回填、失败回滚、一致性备份恢复与 integrity_check；没有迁移或读取用户的 workbench.db。
- 官方 npm 安装已验证：package-lock.json 校验通过，3 个测试依赖安装成功。GitHub Actions 首轮 Linux 检查暴露 B02 完成回调覆盖 B03 新路由的前端竞态；增加重载前后路由校验后，本地 298 项测试、浏览器 B01–B10、远端 push 与 PR 工作流均通过。

本地详细证据（忽略入库）：`.scratch/browser-report/results.json`、两张桌面截图、`.scratch/product-evaluation-observability-20260913-1245/results.json`、`evaluation.db`、`HUMAN_REVIEW.md`。这些证据是合成测试结果，不能用于宣称真实写作质量提高。

## 复现命令

```bash
python3 -m pip install -r requirements-test.txt
python3 scripts/check_clean.py
npm --prefix tests/browser ci --ignore-scripts --no-audit --no-fund
# 首次按 tests/browser/README.md 安装 Chromium
node tests/browser/smoke.cjs
python3 scripts/evaluate_product.py --output .scratch/product-evaluation-new
```

评估输出目录必须不存在，防止覆盖历史证据。mock 默认无需密钥；真实评估必须显式 `--engine real --config <配置路径>`，并经环境变量或显式 settings 来源提供凭据。

也可显式传入 `--settings workbench/settings.json`，仅把其中的 API Key 与 Base URL 注入评估进程；settings 内容不会复制到结果目录。`--model`、`--timeout-seconds` 与 `--max-retries` 可固定提供方行为，`--case-limit` 可先做容量试跑；这些值和配置/案例 hash 一起记录在 `RUN_METADATA.json`，其余参数及提示词仍由 `--config` 固定。评估默认不重试单次模型调用，避免总等待时间隐式超过角色超时。

## 未完成项与下一步顺序

| 优先级 | 剩余工作 | 完成证据 |
|---|---|---|
| 1 | 原生中文输入法、长中文粘贴、多段选择与键盘细节人工验收；当前只有合成 composition 与桌面截图 | 记录平台、输入法、步骤及结果 |
| 2 | 实际评审者填写新产品案例；回收历史 V1.2 剩余 23 对评审，两个实验分开统计 | 带评审者及时间的评价记录 |
| 3 | 核心验收闭环后，为 F01 本地导出/备份与 F02 写前确认卡落扩展规格 | 产品需求、API/数据设计与验收标准 |

## 使用与升级约束

前后端需要一起更新，旧页面缺少 revision 时会收到明确的刷新提示。支持单服务进程，通过 `python -m workbench.server` 获得实例锁；禁止多个 workers 共享数据库。备份包含本地稿件，不上传仓库。

恢复旧版本只保证内容与原结构来源一致，人工编辑后的段落映射仍是估算。sessionStorage 恢复副本只在当前浏览器标签页会话内保留；重要未保存内容应下载。运行使用开始时的模型适配器；开发期间不要在运行中直接改写提示词文件。
