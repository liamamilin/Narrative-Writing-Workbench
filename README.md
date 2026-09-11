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
| Engine V1 | ✅ 完成 | `docs/10`, `V1_IMPLEMENTATION_REPORT.md` |
| V1.1 消融 | ✅ 完成(盲评进行中) | `docs/14`, `V1_1_ABLATION_REPORT.md` |
| V1.2 干净因果消融 | ✅ 完成(23 对待人工盲评) | `docs/16-18`, `V1_2_RUN_REPORT.md` |
| Product V0 Workbench | ✅ 完成(M0–M10) | `docs/narrative-writing-product-v0-spec/`, `PRODUCT_V0_IMPLEMENTATION_REPORT.md` |
| Product V0.1 Quick Write | ✅ 完成(Q0–Q9) | `docs/narrative-writing-product-v0.1-quick-write-spec/`, `QUICK_WRITE_V0_1_IMPLEMENTATION_REPORT.md` |

## 目录结构

```text
app/            引擎:Architect/WIR/Writer/Critic/Patcher/语言修复/硬门/基准
workbench/      产品层 V0/V0.1:FastAPI + SQLite + 无构建 SPA(引擎藏在 adapter 后)
prompts/        外置提示词(引擎角色 + product_patch + meaning_discovery)
schemas/        WIR / critique / outline JSON Schema
docs/           引擎规范 00-18 + 产品规范 narrative-writing-product-v0-spec/
benchmarks/     测试用例、消融结果、盲评表导出/导入
tests/          pytest(230 项:引擎 + 产品 + Quick Write + Settings)
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
(选服务商会自动填入端点与本机可用模型),或手动:

```bash
cp workbench/settings.example.json workbench/settings.json
# 编辑 settings.json: {"engine":"real","base_url":"...","api_key":"...","model":"..."}
./scripts/launch_workbench.sh
```

> 密钥只存本地 `workbench/settings.json`(已在 `.gitignore` 中,永不入库);
> 服务启动时把它注入进程环境,API 只回传掩码。`scripts/launch_workbench.sh stop` 停止。

体验金路径:Start Writing → 粘贴素材 + 意图 → Create & Write → Generate
Draft → 点选段落 → Revise/Shorter… → Generate Patch → Before/After →
Accept(生成版本)→ Versions → Restore。

硬规则:**AI proposes, user accepts** —— 补丁在 Accept 前绝不改动草稿;
Reject 不留痕;生成/补丁失败不破坏已有正文;Restore 自身可逆;
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
python3 -m pytest tests/ -q        # 263 passed
```

## 阅读顺序

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

`NarrativeWorkbench.app` 是本地包装(不入库)。重建图标:
`python3 scripts/make_icon.py`(需 Pillow;自动生成 .icns 写入 app bundle)。

---

© 2026 milin. All rights reserved.
