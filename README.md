# Narrative Writing Harness & Workbench

一个研究型 LLM 写作系统 + 它的产品层工作台。
A research-oriented LLM writing system, plus its Product V0 desktop web workbench.

核心思想:写作不是 `Prompt → Text`,而是把隐性的写作认知显式化:

```text
Material → Intent → Generate → Read → Review → Patch → Accept
```

引擎内部:`Input → Architect → WIR → Writer → (language repair) → Critic → Patch → Final`
(不模仿具名作者表面风格;优化 `meaning progression > reader-state fidelity > natural prose > stylistic decoration`)

## 当前状态

| 层 | 状态 | 蓝图 |
|---|---|---|
| Engine V1 | ✅ 完成 | `docs/10`, `docs/reports/V1_IMPLEMENTATION_REPORT.md` |
| V1.1 消融 | ✅ 完成(盲评进行中) | `docs/14`, `docs/reports/V1_1_ABLATION_REPORT.md` |
| V1.2 干净因果消融 | ✅ 完成(23 对待人工盲评) | `docs/16-18`, `docs/reports/V1_2_RUN_REPORT.md` |
| Product V0 Workbench | ✅ 完成(M0–M10) | `docs/narrative-writing-product-v0-spec/`, `docs/reports/PRODUCT_V0_IMPLEMENTATION_REPORT.md` |
| Product V0.1 Quick Write | ✅ 完成(Q0–Q9) | `docs/narrative-writing-product-v0.1-quick-write-spec/`, `docs/reports/QUICK_WRITE_V0_1_IMPLEMENTATION_REPORT.md` |
| Product V0.2 Export/Backup | ✅ 完成(E0–E6) | `docs/narrative-writing-product-v0.2-export-backup-spec/`, `docs/reports/PRODUCT_V0_2_BACKUP_RESTORE_IMPLEMENTATION_REPORT.md` |
| Product V0.3 Angle Confirmation | ✅ 完成(A0–A5) | `docs/narrative-writing-product-v0.3-angle-confirmation-spec/`, `docs/reports/PRODUCT_V0_3_ANGLE_CONFIRMATION_IMPLEMENTATION_REPORT.md` |
| Product V0.4 Revision Worklist | ✅ 完成(W0–W6) | `docs/narrative-writing-product-v0.4-revision-worklist-spec/`, `docs/reports/PRODUCT_V0_4_REVISION_WORKLIST_IMPLEMENTATION_REPORT.md` |
| Product V0.5 Evidence Cards | ✅ 完成(E0–E6) | `docs/narrative-writing-product-v0.5-evidence-cards-spec/`, `docs/reports/PRODUCT_V0_5_EVIDENCE_CARDS_IMPLEMENTATION_REPORT.md` |
| Product V0.6 Reader Path | ✅ 工程完成(R0–R6；真实效果待评估) | `docs/narrative-writing-product-v0.6-reader-path-spec/`, `docs/reports/PRODUCT_V0_6_READER_PATH_IMPLEMENTATION_REPORT.md` |
| Product V0.7 Local Idea Box | ✅ 完成(I0–I5) | `docs/narrative-writing-product-v0.7-idea-box-spec/`, `docs/reports/PRODUCT_V0_7_IDEA_BOX_IMPLEMENTATION_REPORT.md` |
| Product V0.8 Article Sharing | ✅ 完成(S0–S6) | `docs/narrative-writing-product-v0.8-sharing-spec/`, `docs/reports/PRODUCT_V0_8_SHARING_IMPLEMENTATION_REPORT.md` |

本轮稳定性修复与剩余验收见 [实施报告](docs/reports/V0_1_STABILIZATION_IMPLEMENTATION_REPORT_2026_09_13.md)，持续进度见 [开发日志](docs/reports/DEVELOPMENT_PROGRESS.md)。

产品真实调用：Quick Write 先发现意义并评审命题，再生成结构与正文；检查是单独动作。旧稿入口直接导入原文后检查和局部修订。操作、阶段、模型调用耗时与可取得的 usage 已可追溯；固定真实模型 12 例工程评估已经完成，人工质量评分仍待填写，详见 [真实模型评估报告](docs/reports/REAL_MODEL_EVALUATION_REPORT_2026_09_13.md)。

Quick Write 的新候选只留在“本次生成”；明确收藏后进入本机 SQLite 选题箱，可搜索、写备注、归档、继续写或打开已关联文章。旧浏览器话题库会在服务端完整确认后幂等迁移。

## 目录结构

```text
app/            引擎:Architect/WIR/Writer/Critic/Patcher/语言修复/硬门/基准
workbench/      产品层 V0/V0.1:FastAPI + SQLite + 无构建 SPA(引擎藏在 adapter 后)
prompts/        外置提示词(引擎角色 + product_patch + meaning_discovery)
schemas/        WIR / critique / outline JSON Schema
docs/           引擎规范 00-18 + 产品规范 narrative-writing-product-v0-spec/
docs/reports/   实现/消融/运行报告(V1、V1.1、V1.2、Product V0/V0.1)
benchmarks/     测试用例、消融结果、盲评表导出/导入
tests/          pytest + 浏览器回归(引擎、产品、Quick Write、提交安全与运行恢复)
runs/           每次引擎运行的全量中间产物
ui/             运行观察面板(Flask,8551,非产品 UI)
```

## 快速开始

### 1. Workbench(产品层,推荐入口)

```bash
pip install -r requirements.txt -r requirements-workbench.txt
./scripts/launch_workbench.sh          # 启动并打开 http://127.0.0.1:8600(幂等)
```

不配置任何密钥即可体验完整交互:默认走内置 **mock 引擎**(离线、确定性)。
服务空闲 30 分钟无任何请求会**自动退出**(下次直接重跑脚本即可;
`WORKBENCH_IDLE_TIMEOUT` 分钟可调,0 关闭)。

切换到**真实引擎**:在浏览器打开的 Settings 页填 Base URL / API Key / Model
(选服务商填入端点；模型清单供参考，也可手填别名),或手动:

```bash
cp workbench/settings.example.json workbench/settings.json
# 编辑 settings.json: {"engine":"real","base_url":"...","api_key":"...","model":"..."}
./scripts/launch_workbench.sh
```

> 密钥只存本地 `workbench/settings.json`(已在 `.gitignore` 中,永不入库);
> 服务启动时把它注入进程环境,API 只回传掩码。`scripts/launch_workbench.sh stop` 停止。

真实模型必须先通过完整生成链路，连接测试或短话题生成不能代表长结构化 JSON 兼容。2026-09-13 的同 API、同任务对照中，OpenCode Go 的 `deepseek-v4-flash` 在 258.76 秒内完成意义发现、命题评审、结构和正文；`mimo-v2.5` 两次打满 6,000 输出 token 后仍返回截断 JSON，在意义发现阶段失败。因此当前交互主链路优先使用 `deepseek-v4-flash` 或其他已完成容量试跑的模型；`mimo-v2.5` 暂不作为长结构生成推荐。详情见[真实模型评估报告](docs/reports/REAL_MODEL_EVALUATION_REPORT_2026_09_13.md)。

Workbench 的超时是每次模型调用的边界，产品适配器不做 SDK 隐式重试；结构校验失败仍可能触发一次显式 JSON 修复调用。运行页会分别记录阶段、调用耗时、usage 和最终失败原因。

体验路径:Quick Write 可直接“开始写”，也可“先看角度”→ 选择/编辑完整角度 → 确认并生成。素材写作路径:Start Writing → 粘贴素材 + 意图 → Create & Write → Generate
Draft → 点选段落 → Revise/Shorter… → Generate Patch → Before/After →
Accept(生成版本)→ Versions → Restore。工作台可把最新保存稿导出为 Markdown/纯文本，版本页也可下载任意历史版本。
正文工具栏的“分享”会先保存当前编辑，再生成不可变文章快照、链接和 PNG 卡片；更新或停止分享后旧链接失效。公开页只显示文章白名单字段。本机地址生成的链接只在本机有效，跨设备分享需要使用手机可访问的部署地址。
检查面板会把问题整理为最多三项优先修订工作单；可定位、处理或跳过，也可先把已满意段落标为“保留原文”。

有材料的观点与分析任务还可运行“检查材料依据”：关键陈述卡会并列展示正文原句、材料关系和可回查的 Source 原句。关系与用户确认状态分开保存；正文或素材变化后旧检查会过期，从卡片发起的修改仍须经过 Before/After 和人工接受。
中栏把生成时的“原定路径”和当前正文的“稿件检查”分开：稿件检查逐段显示作用、认识增量与问题回答关系，可定位重复或推理跳跃，并把可靠定位的问题交给同一套安全修订流程。它是模型诊断，不代表真实读者实验。
设置页的“本地数据”可下载全工作区备份，上传预检后恢复到独立目录；备份不包含模型设置或 API 密钥。

硬规则:**AI proposes, user accepts** —— 补丁在 Accept 前绝不改动草稿;
Reject 保留提案记录、不创建正文版本;生成/补丁失败不破坏已有正文;Restore 自身可逆;
autosave 不产生版本。UI 不暴露 WIR/Critic/Patcher。

### 2. 引擎 CLI

```bash
python3 -m app.cli run --material-file material.md \
  --instruction "父亲不要直接表达支持。" --config config.live.yaml
# 子命令: run / benchmark / review / judge / report
```

模型与角色配置在 `config.live.yaml`(API key 只走环境变量)。

### 3. 消融基准 + 人工盲评

> 注:`benchmarks/` 实验数据与 `runs/` 含个人写作素材,未公开发布;
> 复现研究需自备用例(JSONL,字段见 `app/benchmark.py` 的 case 加载)。

```bash
# V1.2 干净消融(10 例 × 5 变体,共享 WIR/共享草稿)
python3 -m app.cli benchmark --cases benchmarks/smoke_cases.jsonl \
  --clean-ablation --experiment-id v1_2_clean --config config.live.yaml

# 导出匿名盲评表(byte-identical 对自动平手,不入表)
python3 scripts/review_txt.py export --results benchmarks/results/v1_2_clean

# 填完回收 + 聚合(自动并入 auto_tie)
python3 scripts/review_txt.py import --results benchmarks/results/v1_2_clean \
  --file <filled>.txt --reviewer <name>
python3 -m app.cli report --results benchmarks/results/v1_2_clean --reviewer <name>
```

假设:H2-clean(读者状态 WIR > 大纲)、H3-clean(同稿 Critic 增益)、
H4-confirm(GI 增益)、H5(Critic 应作用于 GI 草稿)。盲评结果导入前不解读。

## 测试

```bash
python3 -m pip install -r requirements-test.txt
python3 scripts/check_clean.py    # 从源码副本执行，不依赖私人数据
python3 scripts/mock_server.py    # 独立临时 mock 服务，随机端口
# 浏览器套件的安装与运行见 tests/browser/README.md
python3 scripts/evaluate_product.py --output .scratch/product-evaluation-new
```

浏览器与评估均使用合成数据，mock 通过不代表真实写作质量已验证。当前部署为单服务进程；旧库升级前自动创建一致性备份，迁移与回退规则见 [数据/API 契约](docs/planning/STABILIZATION_API_AND_DATA.md)。

## 阅读顺序

**当前情况与开发规划**:[规划总入口](docs/planning/README.md)（现状检查、稳定性开发计划、产品方向、新功能开发计划；2026-09-13）

**想了解产品是什么**:`docs/PRODUCT_INTRODUCTION.md`(中文,面向读者)
**产品层**:`docs/narrative-writing-product-v0-spec/README.md` →
`PRODUCT_IMPLEMENTATION_TASK.md` → `product/00..10`
**引擎层**:`docs/00` → `docs/12` → `docs/01` → `docs/02`(WIR)→
`docs/03-06` → `docs/09` → 消融规范 `docs/14-18`

编码代理须先读 `AGENTS.md`(规范优先级:Product V0 spec > 引擎规范)。

## V1 假设(已由 V1.1/V1.2 消融检验)

- **H1**:WIR 引导写作优于直接生成
- **H2**:读者状态 WIR 优于传统大纲
- **H3**:Critic + Patch 提升质量且不过度编辑

## 桌面 App(可选)

`NarrativeWorkbench.app` 是本地包装(不入库)。图标源文件为
`assets/app-icon-source.png`;运行 `python3 scripts/make_icon.py` 可重建
`.icns` 并写入 app bundle(需 Pillow)。

---

© 2026 milin. All rights reserved.
