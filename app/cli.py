"""Minimal CLI.

    python -m app.cli run --material-file example.txt --instruction "..."
    python -m app.cli benchmark --cases benchmarks/smoke_cases.jsonl
"""

from __future__ import annotations

import argparse
import sys

from .benchmark import ALL_BASELINES, BenchmarkRunner
from .config import Config
from .pipeline import Pipeline


def _load_config(args) -> Config:
    config = Config.load(args.config) if args.config else Config.default()
    if getattr(args, "provider", None):
        config.provider = args.provider
    return config


def cmd_run(args) -> int:
    config = _load_config(args)
    config.setup_logging()
    if args.material_file:
        material = open(args.material_file, "r", encoding="utf-8").read()
    elif args.material:
        material = args.material
    else:
        print("error: provide --material or --material-file", file=sys.stderr)
        return 2
    constraints = None
    if args.constraints_file:
        import json

        constraints = json.loads(open(args.constraints_file, "r", encoding="utf-8").read())

    pipeline = Pipeline(config)
    result = pipeline.run(
        material=material,
        instruction=args.instruction,
        task_type=args.task_type,
        constraints=constraints,
    )
    print(f"run_id: {result.run_id}")
    print(f"status: {result.status}")
    print(f"patched: {result.patched}")
    print(f"run_dir: {result.run_dir}")
    if result.ok:
        print("--- final ---")
        print(result.final_text)
        return 0
    print("--- errors ---")
    for err in result.errors:
        print(err)
    return 1


def cmd_benchmark(args) -> int:
    config = _load_config(args)
    config.setup_logging()
    from .benchmark import ABLATION_PAIRS
    from .variants import V12_PAIRS, V12_ROWS
    if args.baselines:
        baselines = tuple(args.baselines.split(","))
    elif getattr(args, "clean_ablation", False):
        baselines = V12_ROWS
    elif getattr(args, "ablation", False):
        baselines = ("B0", "B1", "A1", "A2", "A2_GI", "A3")
    else:
        baselines = ("B0", "B1", "B3")
    if getattr(args, "clean_ablation", False):
        pairs = V12_PAIRS
    elif getattr(args, "ablation", False):
        pairs = ABLATION_PAIRS
    else:
        pairs = None
    runner = BenchmarkRunner(config)
    outcome = runner.run(
        cases_path=args.cases,
        baselines=baselines,
        experiment_id=args.experiment_id,
        pairs=pairs,
    )
    print(f"experiment_id: {outcome['experiment_id']}")
    print(f"results_dir: {outcome['dir']}")
    import json

    print(json.dumps(outcome["summary"], ensure_ascii=False, indent=2))
    failed = sum(
        b["failed"] for b in outcome["summary"]["per_baseline"].values()
    )
    return 1 if failed else 0


def cmd_review(args) -> int:
    from .review import review_interactive

    return review_interactive(args.results)


def cmd_judge(args) -> int:
    config = _load_config(args)
    config.setup_logging()
    from .llm_client import build_client
    from .review import run_llm_judge

    return run_llm_judge(args.results, build_client(config), config)


def cmd_report(args) -> int:
    import json

    from .review import write_report

    print(json.dumps(write_report(args.results, reviewer=getattr(args, "reviewer", None)),
                      ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="Narrative Writing Harness V1")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="run the full pipeline on one input")
    run_p.add_argument("--material", help="source material text")
    run_p.add_argument("--material-file", help="path to a text file with the source material")
    run_p.add_argument("--instruction", required=True, help="writing instruction")
    run_p.add_argument("--task-type", default="narrative_commentary")
    run_p.add_argument("--constraints-file", help="JSON file of task constraints")
    run_p.add_argument("--config", help="YAML config file (default: built-in defaults)")
    run_p.add_argument("--provider", choices=["openai", "mock"],
                       help="override configured provider")
    run_p.set_defaults(func=cmd_run)

    bench_p = sub.add_parser("benchmark", help="run the smoke benchmark")
    bench_p.add_argument("--cases", required=True, help="path to smoke_cases.jsonl")
    bench_p.add_argument("--baselines", help=f"comma list from {ALL_BASELINES} (default: B0,B1,B3)")
    bench_p.add_argument("--ablation", action="store_true",
                         help="run V1.1 ablation set B0,B1,A1,A2,A2_GI,A3 with "
                              "docs/14 §6 pairwise packaging")
    bench_p.add_argument("--clean-ablation", action="store_true",
                         help="run V1.2 clean causal ablation A1,A2,A3,WGI,GI_A3 "
                              "with shared WIR / shared draft (docs/16)")
    bench_p.add_argument("--experiment-id", default=None)
    bench_p.add_argument("--config", help="YAML config file")
    bench_p.add_argument("--provider", choices=["openai", "mock"])
    bench_p.set_defaults(func=cmd_benchmark)

    review_p = sub.add_parser(
        "review", help="interactive human blind review of pairwise packets")
    review_p.add_argument("--results", required=True,
                          help="benchmark results dir (contains pairwise_packets.jsonl)")
    review_p.set_defaults(func=cmd_review)

    judge_p = sub.add_parser(
        "judge", help="run the optional LLM pairwise judge (advisory)")
    judge_p.add_argument("--results", required=True)
    judge_p.add_argument("--config", help="YAML config file")
    judge_p.add_argument("--provider", choices=["openai", "mock"])
    judge_p.set_defaults(func=cmd_judge)

    report_p = sub.add_parser(
        "report", help="aggregate judgments.jsonl into win-rate summary")
    report_p.add_argument("--results", required=True)
    report_p.add_argument("--reviewer", default=None,
                          help="filter judgments by reviewer (e.g. chatgpt, human)")
    report_p.set_defaults(func=cmd_report)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
