# 产品效果人工评审协议

日期：2026-09-13。适用范围：Product V0/V0.1 三类入口的固定案例评估。本协议只处理人工质量评分，不改变引擎、自动审阅或产品行为。

## 目的与边界

工程运行成功不能证明写作质量。评审者需要看到题目或素材、写作要求和待评文本，但不应提前看到模型名称、自动审阅结论、运行状态、耗时、operation 记录或原案例编号。匿名评审工具因此把可分享的评审包与私有案例映射分开保存。

工具不会生成或猜测人工分数。汇总只接受具名评审者、带时区的 ISO 8601 时间和所有适用维度的 1–5 整数分；空值、越界值、错误维度、缺失案例或来源 hash 不一致都会终止汇总。

## 评分维度

| 维度 | 适用入口 | 判断重点 |
|---|---|---|
| 命题/推进 | Quick Write、有素材写作 | 命题是否具体，正文是否持续产生意义推进 |
| 可辩护性 | 全部 | 判断是否受题目/素材支持，是否臆造事实或过度解释 |
| 保留价值 | 全部 | 有价值的素材、动作、原句和意义关系是否得到保留及使用 |
| 补丁效果 | 旧稿修订 | 局部修改是否改善目标问题，且没有伤害上下文或越界 |

评分标尺固定为整数 1–5：1 表示明显不满足，3 表示基本可用但有问题，5 表示表现稳定。不适用维度不会出现在评分模板中。

## 评审材料生成

每次使用新的输出路径，避免覆盖历史证据。私有映射必须在评审包目录之外，不要随评审包交给评审者。

```bash
python3 scripts/product_human_review.py prepare \
  --results .scratch/product-evaluation-real-<run>/results.json \
  --output .scratch/product-human-review-<run> \
  --key .scratch/product-human-review-<run>-private-key.json \
  --seed 20260913
```

生成物：

- `REVIEW_PACKET.md`：匿名并按固定种子重排的输入、正文或补丁；
- `RATINGS.json`：评审者填写的结构化评分模板；
- `MANIFEST.json`：公开的 packet id、维度、顺序和来源 hash；
- 独立私有 key：匿名编号到原案例/入口的映射及同一来源 hash。

固定 seed、相同 `results.json` 和案例 fixture 会生成字节一致的评审正文及评分模板。工具拒绝未完成案例、重复案例、入口或验收标准不一致的结果。

## 回收与汇总

评审者只修改评审包中的 `RATINGS.json`：填写 `reviewer`、`reviewed_at`、每项 `scores` 和可选 `comments`。完成后由保管私有映射的人运行：

```bash
python3 scripts/product_human_review.py summarize \
  --packet .scratch/product-human-review-<run> \
  --key .scratch/product-human-review-<run>-private-key.json \
  --output .scratch/product-human-review-<run>-summary
```

输出 `summary.json` 和 `SUMMARY.md`，包含总体维度均值、三类入口均值、恢复后的原案例编号、分项分数与评语。自动 PASS、模型状态和运行耗时不参与计算。

多名评审者必须各自保留独立评分文件与汇总目录，不覆盖他人结果。跨评审者一致性和最终质量放行应在至少两份独立结果回收后另行统计；在此之前，项目状态保持“人工评价待回收”。

## 当前真实运行

`gpt-oss:120b-cloud` 的 12 例工程结果已在本地生成匿名包：

- 评审包：`.scratch/product-human-review-gptoss-20260913/`
- 私有映射：`.scratch/product-human-review-gptoss-20260913-private-key.json`
- packet id：`db7c1f2964ed9bdbf8a5`

评分模板仍为空。以上路径受 `.gitignore` 保护，只记录位置和 hash 链路，不把真实评估正文或人工身份提交到仓库。
