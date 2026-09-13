"""Bounded 12-case product smoke + human worksheet. Mock is the safe default.

Real mode requires explicit --engine real --config path; credentials use env.
The report retains failures and unknown usage, and never invents human ratings.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from workbench import settings
    from workbench.db import Database
    from workbench.engine.mock import MockWritingEngine
    from workbench.service import Service
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=('mock', 'real'), default='mock')
    parser.add_argument('--config')
    parser.add_argument('--model', help='real mode only: fixed model override for every role')
    parser.add_argument('--timeout-seconds', type=float,
                        help='real mode only: fixed provider timeout for every role')
    parser.add_argument('--max-retries', type=int, default=0,
                        help='real mode provider retries per call (default: 0)')
    parser.add_argument('--case-limit', type=int,
                        help='run only the first N cases for a capacity pilot')
    parser.add_argument(
        '--settings',
        help='real mode only: local Workbench settings used as the credential/endpoint source')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.engine == 'real' and not args.config:
        parser.error('real mode requires an explicit --config')
    if args.settings and args.engine != 'real':
        parser.error('--settings is only valid with --engine real')
    if (args.model or args.timeout_seconds is not None) and args.engine != 'real':
        parser.error('--model/--timeout-seconds are only valid with --engine real')
    if args.timeout_seconds is not None and args.timeout_seconds <= 0:
        parser.error('--timeout-seconds must be positive')
    if args.max_retries < 0:
        parser.error('--max-retries must be non-negative')
    if args.case_limit is not None and args.case_limit <= 0:
        parser.error('--case-limit must be positive')
    if args.settings:
        credentials_path = Path(args.settings)
        try:
            credentials = json.loads(credentials_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f'cannot read --settings: {type(exc).__name__}')
        if credentials.get('api_key'):
            os.environ['OPENAI_API_KEY'] = credentials['api_key']
        if credentials.get('base_url'):
            os.environ['OPENAI_BASE_URL'] = credentials['base_url']
        if not os.environ.get('OPENAI_API_KEY') or not os.environ.get('OPENAI_BASE_URL'):
            parser.error('--settings must provide api_key and base_url')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)  # do not overwrite prior evidence
    settings.SETTINGS_PATH = output / 'unused-settings.json'
    if args.engine == 'real':
        from workbench.engine.real import RealWritingEngine
        engine = RealWritingEngine(args.config, max_retries=args.max_retries)
        for role in engine.config.roles.values():
            if args.model:
                role.model = args.model
            if args.timeout_seconds is not None:
                role.timeout_seconds = args.timeout_seconds
    else:
        engine = MockWritingEngine()
    db = Database(output / 'evaluation.db')
    svc = Service(db, engine)
    cases_path = ROOT / 'tests/fixtures/product_evaluation_cases.json'
    cases_bytes = cases_path.read_bytes()
    all_cases = json.loads(cases_bytes)
    cases = all_cases[:args.case_limit] if args.case_limit else all_cases
    metadata = {
        'started_at': datetime.now(timezone.utc).isoformat(),
        'engine': args.engine,
        'case_count': len(cases),
        'available_case_count': len(all_cases),
        'cases_sha256': hashlib.sha256(cases_bytes).hexdigest(),
        'config_sha256': (hashlib.sha256(Path(args.config).read_bytes()).hexdigest()
                          if args.config else None),
        'credential_source': 'local_settings' if args.settings else 'environment',
        'model_override': args.model,
        'timeout_seconds_override': args.timeout_seconds,
        'max_retries': args.max_retries,
    }
    (output / 'RUN_METADATA.json').write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2))
    rows = []
    try:
        for case in cases:
            start = time.monotonic()
            row = {'case': case['id'], 'mode': case['input']['input_mode'], 'engine': args.engine,
                   'criterion': case['criterion'], 'human_rating': None,
                   'operations': []}
            def capture_operation(result):
                operation_id = result.get('operation_id')
                if operation_id:
                    row['operations'].append(svc.operation_detail(tid, operation_id))
            try:
                tid = svc.create_task(case['input'])['id']; row['task_id'] = tid
                if row['mode'] != 'draft_revision':
                    capture_operation(svc.generate(tid))
                review = svc.review(tid)
                capture_operation(review)
                row['review_id'] = review['id']
                draft = svc.task_detail(tid)['draft']
                row['draft_before'] = draft['working_content']
                if row['mode'] == 'draft_revision':
                    proposed = svc.propose_patch(tid, {
                        'base_version_id': draft['current_version_id'], 'expected_revision': draft['revision'],
                        'selection': {'paragraph_start': 2, 'paragraph_end': 2},
                        'instruction': case['input']['instruction'], 'review_id': review['id']})
                    capture_operation(proposed)
                    row['proposal'] = proposed
                    assert svc.task_detail(tid)['draft']['working_content'] == draft['working_content']
                    accepted = svc.accept_patch(proposed['patch_id'])
                    row['draft_after'] = accepted['content']
                    assert accepted['content'].split('\n\n')[0] == draft['working_content'].split('\n\n')[0]
                row['status'] = 'completed'
            except Exception as exc:
                row['status'] = 'failed'; row['error_code'] = getattr(exc, 'code', type(exc).__name__)
                row['error'] = str(exc)
            if row.get('task_id'):
                operation_ids = svc.db.q(
                    "SELECT id FROM writing_operations WHERE task_id=? ORDER BY rowid",
                    (row['task_id'],))
                row['operations'] = [
                    svc.operation_detail(row['task_id'], item['id'])
                    for item in operation_ids]
            row['elapsed_ms'] = round((time.monotonic() - start) * 1000)
            rows.append(row)
            (output / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
            print(case['id'], row['status'], flush=True)
        worksheet = '# 产品效果人工评审索引\n\n'
        worksheet += f'运行模式：{args.engine}。mock 只验证流程，不能用于评价真实写作效果。评分必须由实际评审者填写；usage 未取得时保持未知。\n\n'
        worksheet += ('正式评分前，请用 `scripts/product_human_review.py prepare` 生成匿名、随机排序的评审包，并把私有映射保存在评审包目录之外。不要直接查看本目录的模型、自动审阅或 operation 信息后评分。\n\n')
        worksheet += '| 案例 | 运行 | 命题/推进 1–5 | 可辩护性 1–5 | 保留价值 1–5 | 补丁效果 1–5 | 评语/评审者 |\n|---|---|---|---|---|---|---|\n'
        for row in rows:
            worksheet += f'| {row["case"]} | {row["status"]} | 待评 | 待评 | 待评 | 待评 | |\n'
        (output / 'HUMAN_REVIEW.md').write_text(worksheet)
        return 1 if any(r['status'] == 'failed' for r in rows) else 0
    finally:
        db.conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
