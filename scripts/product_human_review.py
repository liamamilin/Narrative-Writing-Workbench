"""Prepare and summarize blind human review for product evaluation runs.

The reviewer packet deliberately excludes engine names, automatic review
decisions, operation data, timings, and original case identifiers. The private
key must be stored outside the packet directory and is only needed when ratings
are summarized.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES = ROOT / "tests/fixtures/product_evaluation_cases.json"

SCHEMA_VERSION = 1
V2_SCHEMA_VERSION = 2
DIMENSIONS = {
    "thesis_progression": "命题/推进",
    "defensibility": "可辩护性",
    "retention": "保留价值",
    "patch_effect": "补丁效果",
}
V2_DIMENSIONS = {
    "thesis_progression": "命题/推进",
    "defensibility": "可辩护性",
    "retention": "保留价值",
    "angle_value": "角度价值",
    "angle_distinctness": "角度区分度",
    "angle_defensibility": "角度可辩护性",
    "selection_confidence": "选择信心",
    "target_improvement": "目标改善",
    "context_preservation": "上下文保留",
    "scope_control": "范围控制",
}
V2_KIND_DIMENSIONS = {
    "draft": ("thesis_progression", "defensibility", "retention"),
    "angle_set": ("angle_value", "angle_distinctness",
                   "angle_defensibility", "selection_confidence"),
    "patch": ("target_improvement", "context_preservation", "scope_control"),
}
ANGLE_FIELDS = ("label", "mechanism", "core_question", "deep_meaning",
                "boundary", "reader_end_state")
APPLICABLE = {
    "topic_only": ("thesis_progression", "defensibility", "retention"),
    "source_grounded": ("thesis_progression", "defensibility", "retention"),
    "draft_revision": ("defensibility", "retention", "patch_effect"),
}
MODE_NAMES = {
    "topic_only": "Quick Write",
    "source_grounded": "有素材写作",
    "draft_revision": "旧稿修订",
}


class ReviewDataError(ValueError):
    """Raised when review inputs are incomplete or inconsistent."""


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReviewDataError(f"无法读取 {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReviewDataError(f"JSON 格式错误 {path}: {exc}") from exc


def _write_json(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _stable_order(case_ids, seed):
    return sorted(
        case_ids,
        key=lambda case_id: hashlib.sha256(
            f"{seed}\0{case_id}".encode("utf-8")).digest(),
    )


def _fenced(value):
    text = str(value).strip()
    fence = "```"
    while fence in text:
        fence += "`"
    return f"{fence}text\n{text}\n{fence}"


def _require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ReviewDataError(f"{field} 必须是非空文本")
    return value


def _load_sources(results_path, cases_path):
    results = _read_json(results_path)
    cases = _read_json(cases_path)
    if not isinstance(results, list) or not results:
        raise ReviewDataError("results 必须是非空数组")
    if not isinstance(cases, list) or not cases:
        raise ReviewDataError("cases 必须是非空数组")

    cases_by_id = {}
    for case in cases:
        if not isinstance(case, dict):
            raise ReviewDataError("每个 case 必须是对象")
        case_id = _require_text(case.get("id"), "case.id")
        if case_id in cases_by_id:
            raise ReviewDataError(f"重复 case id: {case_id}")
        cases_by_id[case_id] = case

    results_by_id = {}
    for row in results:
        if not isinstance(row, dict):
            raise ReviewDataError("每个 result 必须是对象")
        case_id = _require_text(row.get("case"), "result.case")
        if case_id in results_by_id:
            raise ReviewDataError(f"重复 result case: {case_id}")
        if case_id not in cases_by_id:
            raise ReviewDataError(f"results 中存在未知 case: {case_id}")
        if row.get("status") != "completed":
            raise ReviewDataError(f"case {case_id} 未完成，不能进入质量评分")
        case = cases_by_id[case_id]
        mode = case.get("input", {}).get("input_mode")
        if mode not in APPLICABLE:
            raise ReviewDataError(f"case {case_id} 的 input_mode 不受支持: {mode}")
        if row.get("mode") != mode:
            raise ReviewDataError(f"case {case_id} 的 mode 与输入不一致")
        if row.get("criterion") != case.get("criterion"):
            raise ReviewDataError(f"case {case_id} 的 criterion 与输入不一致")
        _require_text(row.get("draft_before"), f"{case_id}.draft_before")
        if mode == "draft_revision":
            _require_text(row.get("draft_after"), f"{case_id}.draft_after")
            proposal = row.get("proposal")
            if not isinstance(proposal, dict):
                raise ReviewDataError(f"{case_id}.proposal 必须是对象")
            _require_text(proposal.get("before"), f"{case_id}.proposal.before")
            _require_text(proposal.get("after"), f"{case_id}.proposal.after")
        results_by_id[case_id] = row
    return cases_by_id, results_by_id


def _case_markdown(label, case, row):
    request = case["input"]
    mode = request["input_mode"]
    lines = [f"## {label}", "", f"评估关注：{case['criterion']}", ""]
    if mode == "topic_only":
        lines += ["写作题目：", "", _fenced(request["topic"]), "", "生成正文：", "",
                  _fenced(row["draft_before"]), ""]
    elif mode == "source_grounded":
        lines += ["提供素材：", "", _fenced(request["material"]), "", "写作要求：", "",
                  _fenced(request["instruction"]), "", "生成正文：", "",
                  _fenced(row["draft_before"]), ""]
    else:
        proposal = row["proposal"]
        lines += ["修订前全文：", "", _fenced(request["material"]), "", "修改要求：", "",
                  _fenced(request["instruction"]), "", "修改范围原文：", "",
                  _fenced(proposal["before"]), "", "建议替换为：", "",
                  _fenced(proposal["after"]), "", "接受补丁后的全文：", "",
                  _fenced(row["draft_after"]), ""]
    names = "、".join(DIMENSIONS[item] for item in APPLICABLE[mode])
    lines += [f"本例评分维度：{names}。", ""]
    return "\n".join(lines)


def prepare_review(results_path, cases_path, output_dir, key_path, seed):
    """Create a reviewer-safe packet and a separate private mapping key."""
    results_path = Path(results_path)
    cases_path = Path(cases_path)
    output_dir = Path(output_dir)
    key_path = Path(key_path)
    if output_dir.exists():
        raise ReviewDataError(f"输出目录已存在: {output_dir}")
    if key_path.exists():
        raise ReviewDataError(f"私有映射已存在: {key_path}")
    resolved_output = output_dir.resolve()
    resolved_key = key_path.resolve()
    if resolved_key == resolved_output or resolved_output in resolved_key.parents:
        raise ReviewDataError("私有映射必须保存在评审包目录之外")

    cases_by_id, results_by_id = _load_sources(results_path, cases_path)
    ordered_ids = _stable_order(results_by_id, seed)
    results_hash = _sha256(results_path)
    cases_hash = _sha256(cases_path)
    packet_id = hashlib.sha256(
        f"product-review-v{SCHEMA_VERSION}\0{results_hash}\0{cases_hash}\0{seed}".encode(
            "utf-8")
    ).hexdigest()[:20]
    entries = []
    sections = []
    rating_rows = []
    for index, case_id in enumerate(ordered_ids, start=1):
        label = f"R{index:02d}"
        case = cases_by_id[case_id]
        row = results_by_id[case_id]
        mode = case["input"]["input_mode"]
        entries.append({"label": label, "case": case_id, "mode": mode})
        sections.append(_case_markdown(label, case, row))
        rating_rows.append({
            "label": label,
            "scores": {dimension: None for dimension in APPLICABLE[mode]},
            "comments": "",
        })

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "packet_id": packet_id,
        "case_count": len(entries),
        "labels": [entry["label"] for entry in entries],
        "dimensions": DIMENSIONS,
        "scale": {"minimum": 1, "maximum": 5},
        "source_results_sha256": results_hash,
        "source_cases_sha256": cases_hash,
    }
    ratings = {
        "schema_version": SCHEMA_VERSION,
        "packet_id": packet_id,
        "reviewer": "",
        "reviewed_at": "",
        "ratings": rating_rows,
    }
    private_key = {
        "schema_version": SCHEMA_VERSION,
        "packet_id": packet_id,
        "seed": str(seed),
        "source_results": str(results_path),
        "source_results_sha256": results_hash,
        "source_cases": str(cases_path),
        "source_cases_sha256": cases_hash,
        "entries": entries,
    }
    introduction = """# 产品效果匿名人工评审包

请独立评价下面的文本，不参考模型名称、自动审阅结论、运行状态或耗时。案例顺序已经用固定种子重排，原始案例编号保存在评审包之外的私有映射中。

在 `RATINGS.json` 填写评审者、带时区的 ISO 8601 评审时间，以及每个案例列出的分数。分数必须是 1–5 的整数：1 表示明显不满足，3 表示基本可用但有问题，5 表示表现稳定。不要为未列出的维度评分。

评分维度：

- 命题/推进：中心命题是否具体，正文是否持续产生新的意义推进。
- 可辩护性：判断是否由题目或素材支持，是否避免臆造关键事实和过度解释。
- 保留价值：有价值的素材、动作、原句或意义关系是否被保留并有效使用。
- 补丁效果：局部修订是否改善目标问题，且没有伤害上下文或越界修改。

"""
    output_dir.mkdir(parents=True, exist_ok=False)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    (output_dir / "REVIEW_PACKET.md").write_text(
        introduction + "\n".join(sections), encoding="utf-8")
    _write_json(output_dir / "RATINGS.json", ratings)
    _write_json(output_dir / "MANIFEST.json", manifest)
    _write_json(key_path, private_key)
    return manifest


def _load_sources_v2(results_path, cases_path):
    """Load results for the core packet without exposing private metadata."""
    cases_by_id, results_by_id = _load_sources(results_path, cases_path)
    for case_id, row in results_by_id.items():
        options = row.get("angle_options")
        if options is None:
            continue
        if cases_by_id[case_id]["input"].get("input_mode") != "topic_only":
            raise ReviewDataError(f"case {case_id} 的 angle_options 只能用于 Quick Write")
        if not isinstance(options, dict) or not isinstance(options.get("candidates"), list):
            raise ReviewDataError(f"{case_id}.angle_options.candidates 必须是数组")
        candidates = options["candidates"]
        if not 3 <= len(candidates) <= 5:
            raise ReviewDataError(f"{case_id} 必须有 3–5 个角度候选")
        seen = set()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ReviewDataError(f"{case_id} 的角度候选必须是对象")
            candidate_id = _require_text(candidate.get("id"), f"{case_id}.candidate.id")
            if candidate_id in seen:
                raise ReviewDataError(f"{case_id} 存在重复角度候选")
            seen.add(candidate_id)
            for field in ANGLE_FIELDS:
                _require_text(candidate.get(field), f"{case_id}.candidate.{field}")
    return cases_by_id, results_by_id


def _v2_items(cases_by_id, results_by_id, seed):
    items = []
    for case_id, row in results_by_id.items():
        mode = cases_by_id[case_id]["input"]["input_mode"]
        items.append({"case": case_id, "mode": mode,
                      "kind": "patch" if mode == "draft_revision" else "draft"})
        if row.get("angle_options") is not None:
            items.append({"case": case_id, "mode": mode, "kind": "angle_set"})
    return sorted(items, key=lambda item: hashlib.sha256(
        f"{seed}\0{item['case']}\0{item['kind']}".encode("utf-8")).digest())


def _v2_case_markdown(label, item, case, row, candidate_codes):
    request = case["input"]
    kind = item["kind"]
    lines = [f"## {label}", "", f"评估类型：{kind}",
             f"评估关注：{case['criterion']}", ""]
    if kind == "draft":
        mode = request["input_mode"]
        if mode == "topic_only":
            lines += ["写作题目：", "", _fenced(request["topic"]), ""]
        else:
            lines += ["提供素材：", "", _fenced(request["material"]), "",
                      "写作要求：", "", _fenced(request["instruction"]), ""]
        lines += ["生成正文：", "", _fenced(row["draft_before"]), ""]
    elif kind == "angle_set":
        lines += ["写作题目：", "", _fenced(request["topic"]), "",
                  "候选角度（请在 RATINGS.json 选择一个最值得继续写的候选）：", ""]
        for code, candidate in zip(candidate_codes, row["angle_options"]["candidates"]):
            lines += [f"### {code}", "", f"主张：{candidate['label']}",
                      f"机制：{candidate['mechanism']}",
                      f"核心问题：{candidate['core_question']}",
                      f"深层含义：{candidate['deep_meaning']}",
                      f"边界：{candidate['boundary']}",
                      f"读者收获：{candidate['reader_end_state']}", ""]
    else:
        proposal = row["proposal"]
        lines += ["修订前全文：", "", _fenced(request["material"]), "",
                  "修改要求：", "", _fenced(request["instruction"]), "",
                  "修改范围原文：", "", _fenced(proposal["before"]), "",
                  "建议替换为：", "", _fenced(proposal["after"]), "",
                  "接受补丁后的全文：", "", _fenced(row["draft_after"]), ""]
    dimensions = "、".join(V2_DIMENSIONS[item_name]
                            for item_name in V2_KIND_DIMENSIONS[kind])
    lines += [f"本例评分维度：{dimensions}。", ""]
    return "\n".join(lines)


def prepare_review_v2(results_path, cases_path, output_dir, key_path, seed):
    """Create a v2 packet covering drafts, angle sets, and local patches."""
    results_path, cases_path = Path(results_path), Path(cases_path)
    output_dir, key_path = Path(output_dir), Path(key_path)
    if output_dir.exists():
        raise ReviewDataError(f"输出目录已存在: {output_dir}")
    if key_path.exists():
        raise ReviewDataError(f"私有映射已存在: {key_path}")
    resolved_output, resolved_key = output_dir.resolve(), key_path.resolve()
    if resolved_key == resolved_output or resolved_output in resolved_key.parents:
        raise ReviewDataError("私有映射必须保存在评审包目录之外")
    cases_by_id, results_by_id = _load_sources_v2(results_path, cases_path)
    items = _v2_items(cases_by_id, results_by_id, seed)
    results_hash, cases_hash = _sha256(results_path), _sha256(cases_path)
    packet_id = hashlib.sha256(
        f"product-review-v{V2_SCHEMA_VERSION}\0{results_hash}\0{cases_hash}\0{seed}".encode(
            "utf-8")).hexdigest()[:20]
    sections, rating_rows, private_items = [], [], []
    for index, item in enumerate(items, start=1):
        label = f"R{index:02d}"
        item = {**item, "label": label}
        row = results_by_id[item["case"]]
        candidate_codes = []
        if item["kind"] == "angle_set":
            candidate_codes = [f"C{n:02d}" for n in range(1, len(row["angle_options"]["candidates"]) + 1)]
            item["candidate_map"] = dict(zip(
                candidate_codes, [c["id"] for c in row["angle_options"]["candidates"]]))
        private_items.append(item)
        sections.append(_v2_case_markdown(label, item, cases_by_id[item["case"]],
                                          row, candidate_codes))
        rating_rows.append({
            "label": label,
            "kind": item["kind"],
            "scores": {name: None for name in V2_KIND_DIMENSIONS[item["kind"]]},
            "preferred_candidate": None if item["kind"] == "angle_set" else "",
            "comments": "",
        })
    manifest = {
        "schema_version": V2_SCHEMA_VERSION,
        "packet_id": packet_id,
        # Count cases represented by this evaluation run. The fixture may
        # contain more cases than a capacity-limited results file.
        "case_count": len(results_by_id),
        "item_count": len(items),
        "labels": [item["label"] for item in private_items],
        "dimensions": V2_DIMENSIONS,
        "kind_dimensions": V2_KIND_DIMENSIONS,
        "kind_counts": {kind: sum(item["kind"] == kind for item in items)
                         for kind in V2_KIND_DIMENSIONS},
        "scale": {"minimum": 1, "maximum": 5},
        "source_results_sha256": results_hash,
        "source_cases_sha256": cases_hash,
    }
    private_key = {
        "schema_version": V2_SCHEMA_VERSION,
        "packet_id": packet_id,
        "seed": str(seed),
        "source_results": str(results_path),
        "source_results_sha256": results_hash,
        "source_cases": str(cases_path),
        "source_cases_sha256": cases_hash,
        "items": private_items,
    }
    introduction = """# 产品核心体验匿名人工评审包

请独立评价下面的初稿、写前角度候选或局部修订，不参考模型名称、自动审阅结论、运行状态、耗时或原案例编号。角度候选请在 `RATINGS.json` 的 `preferred_candidate` 中填写最值得继续写的候选代码（如 `C02`）。

评分为 1–5 的整数：1 表示明显不满足，3 表示基本可用但有问题，5 表示表现稳定。只填写当前评估类型列出的维度；不要把其他类型的维度补进来。

"""
    output_dir.mkdir(parents=True, exist_ok=False)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    (output_dir / "REVIEW_PACKET.md").write_text(
        introduction + "\n".join(sections), encoding="utf-8")
    _write_json(output_dir / "RATINGS.json", {
        "schema_version": V2_SCHEMA_VERSION, "packet_id": packet_id,
        "reviewer": "", "reviewed_at": "", "ratings": rating_rows})
    _write_json(output_dir / "MANIFEST.json", manifest)
    _write_json(key_path, private_key)
    return manifest


def _validate_ratings_v2(manifest, key, ratings):
    packet_ids = {item.get("packet_id") for item in (manifest, key, ratings)}
    if packet_ids != {manifest.get("packet_id")} or None in packet_ids:
        raise ReviewDataError("v2 评审文件的 packet_id 不一致")
    if any(item.get("schema_version") != V2_SCHEMA_VERSION
           for item in (manifest, key, ratings)):
        raise ReviewDataError("评审文件 schema_version 不受支持")
    if manifest.get("source_results_sha256") != key.get("source_results_sha256") \
            or manifest.get("source_cases_sha256") != key.get("source_cases_sha256"):
        raise ReviewDataError("评审包与私有映射的来源 hash 不一致")
    reviewer = _require_text(ratings.get("reviewer"), "reviewer").strip()
    reviewed_at = _parse_reviewed_at(ratings.get("reviewed_at"))
    entries = key.get("items")
    supplied_rows = ratings.get("ratings")
    if not isinstance(entries, list) or not isinstance(supplied_rows, list):
        raise ReviewDataError("v2 items 和 ratings 必须是数组")
    expected = {entry.get("label"): entry for entry in entries}
    if None in expected or len(expected) != len(entries):
        raise ReviewDataError("v2 私有映射包含重复或空 label")
    if set(manifest.get("labels", [])) != set(expected):
        raise ReviewDataError("v2 manifest labels 与私有映射不一致")
    supplied = {}
    for row in supplied_rows:
        if not isinstance(row, dict) or row.get("label") in supplied:
            raise ReviewDataError("v2 评分包含重复或无效项目")
        supplied[row["label"]] = row
    if set(supplied) != set(expected):
        raise ReviewDataError("v2 评分项目不完整")
    validated = []
    for label in manifest["labels"]:
        entry, row = expected[label], supplied[label]
        kind = entry.get("kind")
        if kind not in V2_KIND_DIMENSIONS or row.get("kind") != kind:
            raise ReviewDataError(f"{label} 的评估类型不一致")
        scores = row.get("scores")
        required = set(V2_KIND_DIMENSIONS[kind])
        if not isinstance(scores, dict) or set(scores) != required:
            raise ReviewDataError(f"{label} 的评分维度不符合 {kind} 要求")
        clean_scores = {}
        for dimension, score in scores.items():
            if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
                raise ReviewDataError(f"{label}.{dimension} 必须是 1–5 的整数")
            clean_scores[dimension] = score
        preferred = row.get("preferred_candidate", "")
        if kind == "angle_set":
            if preferred not in (entry.get("candidate_map") or {}):
                raise ReviewDataError(f"{label}.preferred_candidate 必须选择一个候选")
        elif preferred not in ("", None):
            raise ReviewDataError(f"{label} 不适用 preferred_candidate")
        comments = row.get("comments", "")
        if not isinstance(comments, str):
            raise ReviewDataError(f"{label}.comments 必须是文本")
        validated.append({**entry, "scores": clean_scores,
                          "preferred_candidate": preferred or None,
                          "comments": comments.strip()})
    return reviewer, reviewed_at, validated


def summarize_review_v2(packet_dir, key_path, ratings_path, output_dir):
    packet_dir, key_path = Path(packet_dir), Path(key_path)
    ratings_path = Path(ratings_path) if ratings_path else packet_dir / "RATINGS.json"
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise ReviewDataError(f"输出目录已存在: {output_dir}")
    manifest = _read_json(packet_dir / "MANIFEST.json")
    key, ratings = _read_json(key_path), _read_json(ratings_path)
    reviewer, reviewed_at, rows = _validate_ratings_v2(manifest, key, ratings)
    by_kind = {}
    for kind, dimensions in V2_KIND_DIMENSIONS.items():
        kind_rows = [row for row in rows if row["kind"] == kind]
        by_kind[kind] = {
            "item_count": len(kind_rows),
            "means": {dimension: _mean([row["scores"][dimension] for row in kind_rows])
                      for dimension in dimensions},
        }
    restored = []
    for row in rows:
        row = dict(row)
        if row["kind"] == "angle_set":
            mapping = row.get("candidate_map") or {}
            row["preferred_candidate_id"] = mapping.get(row["preferred_candidate"])
        row.pop("candidate_map", None)
        restored.append(row)
    summary = {
        "schema_version": V2_SCHEMA_VERSION, "packet_id": manifest["packet_id"],
        "reviewer": reviewer, "reviewed_at": reviewed_at,
        "source_results_sha256": key["source_results_sha256"],
        "source_cases_sha256": key["source_cases_sha256"],
        "case_count": manifest["case_count"], "item_count": len(rows),
        "kinds": by_kind, "ratings": restored,
    }
    md = ["# 产品核心体验人工评审汇总", "", f"评审者：{_md_cell(reviewer)}  ",
          f"评审时间：{reviewed_at}  ", f"评审包：`{manifest['packet_id']}`  ",
          f"评审项目数：{len(rows)}", "", "## 类型汇总", "",
          "| 类型 | 项目数 | 维度均值 |", "|---|---:|---|"]
    for kind, item in by_kind.items():
        means = "；".join(f"{V2_DIMENSIONS[d]} {score:.2f}"
                          for d, score in item["means"].items() if score is not None)
        md.append(f"| {kind} | {item['item_count']} | {means} |")
    md += ["", "## 分项记录", "", "| 项目 | 类型 | 分数 | 首选角度 | 评语 |",
           "|---|---|---|---|---|"]
    for row in restored:
        scores = "；".join(f"{V2_DIMENSIONS[d]} {score}"
                           for d, score in row["scores"].items())
        md.append(f"| {row['case']} / {row['label']} | {row['kind']} | {scores} | "
                  f"{row.get('preferred_candidate_id') or ''} | {_md_cell(row['comments'])} |")
    md += ["", "分数只代表本次具名人工评审；自动审阅、模型状态和运行耗时未参与计算。", ""]
    output_dir.mkdir(parents=True, exist_ok=False)
    _write_json(output_dir / "summary.json", summary)
    (output_dir / "SUMMARY.md").write_text("\n".join(md), encoding="utf-8")
    return summary


def _parse_reviewed_at(value):
    text = _require_text(value, "reviewed_at")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewDataError("reviewed_at 必须是 ISO 8601 时间") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReviewDataError("reviewed_at 必须包含时区")
    return text


def _validate_ratings(manifest, key, ratings):
    packet_ids = {item.get("packet_id") for item in (manifest, key, ratings)}
    if len(packet_ids) != 1 or None in packet_ids:
        raise ReviewDataError("manifest、私有映射与评分文件的 packet_id 不一致")
    if any(item.get("schema_version") != SCHEMA_VERSION for item in (manifest, key, ratings)):
        raise ReviewDataError("评审文件 schema_version 不受支持")
    if manifest.get("source_results_sha256") != key.get("source_results_sha256"):
        raise ReviewDataError("评审包与私有映射的 results hash 不一致")
    if manifest.get("source_cases_sha256") != key.get("source_cases_sha256"):
        raise ReviewDataError("评审包与私有映射的 cases hash 不一致")
    reviewer = _require_text(ratings.get("reviewer"), "reviewer").strip()
    reviewed_at = _parse_reviewed_at(ratings.get("reviewed_at"))

    entries = key.get("entries")
    rows = ratings.get("ratings")
    if not isinstance(entries, list) or not isinstance(rows, list):
        raise ReviewDataError("entries 和 ratings 必须是数组")
    expected = {entry.get("label"): entry for entry in entries}
    if None in expected or len(expected) != len(entries):
        raise ReviewDataError("私有映射包含重复或空 label")
    manifest_labels = manifest.get("labels")
    if (not isinstance(manifest_labels, list)
            or len(manifest_labels) != len(set(manifest_labels))
            or set(manifest_labels) != set(expected)):
        raise ReviewDataError("manifest labels 与私有映射不一致")
    supplied = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ReviewDataError("每项评分必须是对象")
        label = row.get("label")
        if label in supplied:
            raise ReviewDataError(f"重复评分: {label}")
        supplied[label] = row
    if set(supplied) != set(expected):
        missing = sorted(set(expected) - set(supplied))
        extra = sorted(set(supplied) - set(expected))
        raise ReviewDataError(f"评分案例不完整；缺少 {missing}，多出 {extra}")

    validated = []
    for label in manifest_labels:
        entry = expected.get(label)
        if not entry:
            raise ReviewDataError(f"manifest 中存在未知 label: {label}")
        mode = entry.get("mode")
        if mode not in APPLICABLE:
            raise ReviewDataError(f"私有映射中存在未知 mode: {mode}")
        row = supplied[label]
        scores = row.get("scores")
        if not isinstance(scores, dict) or set(scores) != set(APPLICABLE[mode]):
            raise ReviewDataError(f"{label} 的评分维度不符合 {MODE_NAMES[mode]} 要求")
        clean_scores = {}
        for dimension, score in scores.items():
            if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
                raise ReviewDataError(f"{label}.{dimension} 必须是 1–5 的整数")
            clean_scores[dimension] = score
        comments = row.get("comments", "")
        if not isinstance(comments, str):
            raise ReviewDataError(f"{label}.comments 必须是文本")
        validated.append({**entry, "scores": clean_scores, "comments": comments.strip()})
    return reviewer, reviewed_at, validated


def _mean(values):
    return round(sum(values) / len(values), 2) if values else None


def _md_cell(value):
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def summarize_review(packet_dir, key_path, ratings_path, output_dir):
    """Validate completed ratings and create traceable JSON/Markdown summaries."""
    packet_dir = Path(packet_dir)
    key_path = Path(key_path)
    ratings_path = Path(ratings_path) if ratings_path else packet_dir / "RATINGS.json"
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise ReviewDataError(f"输出目录已存在: {output_dir}")
    manifest = _read_json(packet_dir / "MANIFEST.json")
    key = _read_json(key_path)
    ratings = _read_json(ratings_path)
    reviewer, reviewed_at, rows = _validate_ratings(manifest, key, ratings)

    by_mode = {}
    for mode in APPLICABLE:
        mode_rows = [row for row in rows if row["mode"] == mode]
        by_mode[mode] = {
            "name": MODE_NAMES[mode],
            "case_count": len(mode_rows),
            "means": {
                dimension: _mean([row["scores"][dimension] for row in mode_rows])
                for dimension in APPLICABLE[mode]
            },
        }
    overall = {
        dimension: _mean([
            row["scores"][dimension] for row in rows if dimension in row["scores"]
        ])
        for dimension in DIMENSIONS
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "packet_id": manifest["packet_id"],
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "source_results_sha256": key["source_results_sha256"],
        "source_cases_sha256": key["source_cases_sha256"],
        "case_count": len(rows),
        "overall_means": overall,
        "modes": by_mode,
        "ratings": rows,
    }

    md = [
        "# 产品效果人工评审汇总",
        "",
        f"评审者：{_md_cell(reviewer)}  ",
        f"评审时间：{reviewed_at}  ",
        f"评审包：`{manifest['packet_id']}`  ",
        f"案例数：{len(rows)}",
        "",
        "## 入口汇总",
        "",
        "| 入口 | 案例数 | 维度均值 |",
        "|---|---:|---|",
    ]
    for mode in APPLICABLE:
        item = by_mode[mode]
        means = "；".join(
            f"{DIMENSIONS[dimension]} {score:.2f}"
            for dimension, score in item["means"].items()
            if score is not None
        )
        md.append(f"| {item['name']} | {item['case_count']} | {means} |")
    md += [
        "",
        "## 分项记录",
        "",
        "| 案例 | 入口 | 分数 | 评语 |",
        "|---|---|---|---|",
    ]
    for row in sorted(rows, key=lambda item: item["case"]):
        scores = "；".join(
            f"{DIMENSIONS[dimension]} {score}"
            for dimension, score in row["scores"].items()
        )
        md.append(
            f"| {row['case']} | {MODE_NAMES[row['mode']]} | {scores} | "
            f"{_md_cell(row['comments'])} |"
        )
    md += [
        "",
        "分数只代表本次具名人工评审；工程 PASS、自动审阅和模型状态未参与计算。",
        "",
    ]

    output_dir.mkdir(parents=True, exist_ok=False)
    _write_json(output_dir / "summary.json", summary)
    (output_dir / "SUMMARY.md").write_text("\n".join(md), encoding="utf-8")
    return summary


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="生成匿名评审包与独立私有映射")
    prepare.add_argument("--results", required=True)
    prepare.add_argument("--cases", default=str(DEFAULT_CASES))
    prepare.add_argument("--output", required=True, help="必须不存在的评审包目录")
    prepare.add_argument("--key", required=True, help="评审包目录之外的私有映射文件")
    prepare.add_argument("--seed", default="20260913")
    prepare.add_argument("--schema-version", choices=("1", "2"), default="1",
                         help="v2 增加角度候选和分类型修订维度；默认保持 v1 兼容")

    summarize = subparsers.add_parser("summarize", help="校验评分并生成汇总")
    summarize.add_argument("--packet", required=True)
    summarize.add_argument("--key", required=True)
    summarize.add_argument("--ratings", help="默认使用评审包内的 RATINGS.json")
    summarize.add_argument("--output", required=True, help="必须不存在的汇总目录")
    return parser


def main():
    parser = _parser()
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            if args.schema_version == "2":
                result = prepare_review_v2(args.results, args.cases, args.output,
                                           args.key, args.seed)
            else:
                result = prepare_review(args.results, args.cases, args.output,
                                        args.key, args.seed)
            print(f"prepared {result['case_count']} anonymous cases: {args.output}")
        else:
            manifest = _read_json(Path(args.packet) / "MANIFEST.json")
            if manifest.get("schema_version") == V2_SCHEMA_VERSION:
                result = summarize_review_v2(args.packet, args.key, args.ratings,
                                             args.output)
            else:
                result = summarize_review(args.packet, args.key, args.ratings,
                                          args.output)
            print(f"summarized {result['case_count']} rated cases: {args.output}")
        return 0
    except ReviewDataError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
