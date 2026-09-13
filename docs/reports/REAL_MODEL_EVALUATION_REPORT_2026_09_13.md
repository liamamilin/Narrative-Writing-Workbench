# Product V0.1 真实模型工程评估报告

日期：2026-09-13。范围：固定 12 个合成案例的产品链路、失败留存、阶段观测、耗时和 usage 可得性。本文不填写人工质量评分，也不把工程完成解释为写作质量提升。

## 最终运行配置

| 项目 | 固定值 |
|---|---|
| 模型 | `gpt-oss:120b-cloud`（经本机 Ollama OpenAI 兼容端点） |
| 案例 | Q01–Q04、S01–S04、D01–D04 |
| 超时 | 每次模型调用 120 秒 |
| SDK 重试 | 0 |
| 配置 SHA-256 | `432ccef030c1d36f11e95cdee8be9e231185593aa733efca78fa21136cadf129` |
| 案例 SHA-256 | `193fac6c65c1ef08099ebc956badcaf18042fe2fa3b963209bce5570496c9e73` |
| 原始证据 | `.scratch/product-evaluation-real-gptoss-20260913-1327/` |

凭据来自本机 `workbench/settings.json`，只在评估进程中注入 API Key 与 Base URL。结果目录没有复制 settings；扫描结果未发现 `api_key`、`Authorization`、`Bearer ` 或常见 `sk-` 前缀。

## 工程结果

| 指标 | 结果 |
|---|---:|
| 完成案例 | 12 / 12 |
| Quick Write | 4 / 4 |
| 有素材写作 | 4 / 4 |
| 旧稿修订 | 4 / 4 |
| 成功 operation | 24 / 24 |
| 模型调用 | 40 / 40 completed |
| 案例累计耗时 | 151.71 秒 |
| 单例耗时中位数 | 11.31 秒 |
| 单例范围 | 3.34–24.58 秒 |

operation 包括 generate 8、review 12、patch 4。8 个生成 operation 的结构生成、中文检查和输出硬门全部通过，且未使用结构修复或语言修复；4 个 Quick Write 命题评审均接受。8 篇生成稿的检查结论为 PASS，其中 2 篇仍返回一项非阻断问题。4 篇导入旧稿均为 PATCH_REQUIRED，共定位 5 项问题，并完成提案、接受及“只修改指定段落”的自动断言。

这些状态只证明产品管线和既有自动规则走通。命题是否有推进、文本是否可辩护、哪些原句值得保留，以及补丁是否真正改善了文章，仍须实际评审者按[人工评分跟踪](REAL_MODEL_EVALUATION_HUMAN_REVIEW_2026_09_13.md)和[匿名评审协议](../planning/PRODUCT_HUMAN_REVIEW_PROTOCOL.md)完成独立评分。

## 调用与 usage

| operation | 数量 | 已知调用 | 未知调用 | 已知 input tokens | 已知 output tokens | 模型耗时 |
|---|---:|---:|---:|---:|---:|---:|
| generate | 8 | 16 | 8 | 35,521 | 24,379 | 120.22 秒 |
| review | 12 | 12 | 0 | 46,093 | 5,294 | 27.12 秒 |
| patch | 4 | 4 | 0 | 2,309 | 412 | 3.97 秒 |
| 合计 | 24 | 32 | 8 | 83,923 | 30,085 | 151.31 秒 |

8 次未知均为流式正文调用；当前兼容端点没有在流中返回 usage。已知 token 只是下限，不能拿来计算完整 token 总量或完整费用；本次也没有可验证的单价元数据，因此费用保持未知。

## 容量与配置发现

最终批次前保留了三类失败证据：

1. `mimo-v2.5` 不在当前 Ollama 模型清单中，12 个案例分别在首个 generate/review 操作收到 model not found。目录：`.scratch/product-evaluation-real-20260913-125939/`。
2. `qwen3.8:27b-mlx` 的首次结构化请求在 460.36 秒仍未返回，人工终止试跑。它暴露 SDK 默认重试会使总等待超过角色超时。目录：`.scratch/product-evaluation-real-qwen38-20260913-1305/`。
3. `qwen3.5:9b-mlx` 在 120 秒、零重试的 Q01 试跑中完成了可修复的意义发现，但命题评审和结构调用超时，案例在 372.17 秒后失败。目录：`.scratch/product-evaluation-real-qwen35-pilot-20260913-1318/`。

因此评估器现在默认单次调用不重试，并支持 `--case-limit` 先做容量试跑。模型可用性和完整产品链路必须分别验证；只通过短连接测试不足以进入整批评估。

## Workbench 现场模型对照

2026-09-13 使用同一 OpenCode Go API、同一 topic-only 任务和 300 秒单次超时连续复查，得到可直接比较的产品运行证据：

| 模型 | operation | 结果 | 关键证据 |
|---|---|---|---|
| `mimo-v2.5` | `op_8331ea0fb108` | 失败 | 意义发现首次 208.38 秒、修复 125.69 秒；两次均达到 6,000 输出 token；修复结果在候选角度开头截断并以大量空白耗尽上限；总耗时 334.09 秒 |
| `deepseek-v4-flash` | `op_c055409816c3` | 成功 | 意义发现 69.88 秒、命题评审 29.79 秒、结构 103.93 秒、正文 55.12 秒；结构化阶段一次通过；总耗时 258.76 秒并创建 Draft/Version |

两次运行都使用新产品默认的零 SDK 重试。`mimo-v2.5` 的失败不是 API、Key 或连接错误，而是当前长结构 JSON 请求下的输出稳定性问题；失败后 Draft 与 Version 为空。随后 `deepseek-v4-flash` 在相同 API 和任务上完成全链路，中文检查和输出门均一次通过。

这份单任务对照只支持工程兼容性结论，不能证明 DeepSeek 的文章质量更高。当前模型准入顺序应为：连接测试 → 单案例完整生成 → 结构校验/修复次数与截断检查 → 小批量工程运行 → 独立人工质量评审。`deepseek-v4-flash` 可作为 OpenCode Go 当前交互主链路候选；`mimo-v2.5` 在长结构输出问题解决前不作为完整生成推荐。

## 复现

```bash
python3 scripts/evaluate_product.py \
  --engine real \
  --config config.live.yaml \
  --settings workbench/settings.json \
  --model gpt-oss:120b-cloud \
  --timeout-seconds 120 \
  --max-retries 0 \
  --output .scratch/product-evaluation-real-<new-id>
```

输出目录必须是新路径。运行会调用真实模型；`RUN_METADATA.json` 固定模型覆盖、超时、重试数、案例数及输入 hash，`results.json` 保存成功和失败 operation，`evaluation.db` 保留本地运行记录，`HUMAN_REVIEW.md` 不预填任何评分。

工程运行完成后，用 `scripts/product_human_review.py prepare` 生成匿名评审包；不要让评审者直接从 `results.json` 评分。当前 12 例已生成 packet id `db7c1f2964ed9bdbf8a5`，评分仍为空。
