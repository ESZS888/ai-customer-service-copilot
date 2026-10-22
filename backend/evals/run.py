"""Real API evaluation; saves only demo inputs, outputs and safe metadata.

Run from backend: python -m evals.run --label baseline --output <new-dir>
Existing result directories are never overwritten. Both runs use identical
fixture time and per-thread HTTP transport; no model responses are mocked.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import threading
import time

from evals.score import score


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest(root):
    return {str(path.relative_to(root)).replace('\\', '/'): digest(path)
            for path in sorted((root / 'app').rglob('*.py'))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=2, choices=(1, 2))
    parser.add_argument('--split', choices=('development', 'acceptance'))
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--service', action='store_true', help='Sprint 2: run shared service and persist as evaluation data')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=False)
    cases_path = Path(__file__).with_name('cases.jsonl')
    cases = [json.loads(line) for line in cases_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(cases) == 36 and len({c['case_id'] for c in cases}) == 36
    if args.split:
        cases = [c for c in cases if c['split'] == args.split]
    cases = [{**case, 'repeat_index': index} for index in range(args.repeat) for case in cases]

    # Record snapshot before the first request. Never copy .env or logs.
    before = source_manifest(root)
    shutil.copytree(root / 'app', args.output / 'source_snapshot' / 'app',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(cases_path, args.output / 'cases.jsonl')
    shutil.copy2(Path(__file__).with_name('score.py'), args.output / 'score.py')

    from app.config import settings
    from app.agents import llm_client
    from app.agents.graph import agent_graph
    from app.data.config import get_data_provider
    from app.data import demo_provider
    assert type(get_data_provider()).__name__ == 'DemoDataProvider', 'Evaluation requires demo data.'

    class FixtureDate(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 17, 12, 0, 0, tzinfo=tz)

    demo_provider.datetime = FixtureDate
    local = threading.local()

    def session_for_thread():
        if not hasattr(local, 'session'):
            session = llm_client._build_client()
            original_post = session.post

            def record_post(*pos, **kwargs):
                start = time.perf_counter()
                row = {'model': kwargs.get('json', {}).get('model')}
                try:
                    response = original_post(*pos, **kwargs)
                    row['http_status'] = response.status_code
                    if response.ok:
                        data = response.json()
                        row['usage'] = data.get('usage')
                        row['finish_reason'] = data.get('choices', [{}])[0].get('finish_reason')
                    return response
                except Exception as exc:
                    row['error_type'] = type(exc).__name__
                    raise
                finally:
                    row['seconds'] = round(time.perf_counter() - start, 4)
                    local.calls.append(row)

            session.post = record_post
            local.session = session
        return local.session

    llm_client._get_session = session_for_thread

    def redact(value):
        raw = json.dumps(value, ensure_ascii=False, default=str)
        if settings.llm_api_key:
            raw = raw.replace(settings.llm_api_key, '[REDACTED]')
        return json.loads(raw)

    manifest = {'label': args.label, 'started_at': datetime.now().astimezone().isoformat(),
                'model': settings.llm_model, 'base_url': settings.llm_base_url,
                'data_source': 'evaluation' if args.service else 'demo', 'provider':'DemoDataProvider',
                'execution_path':'chat_service' if args.service else 'agent_graph', 'fixture_date': '2026-10-17T12:00:00',
                'case_hash': digest(cases_path), 'scorer_hash': digest(Path(__file__).with_name('score.py')),
                'source_before': before, 'workers': args.workers, 'case_count': len(cases),
                'split': args.split or 'all', 'repeat': args.repeat,
                'transport': 'same real requests; per-thread sessions; no content/temperature changes'}
    (args.output / 'manifest.json').write_text(json.dumps(redact(manifest), ensure_ascii=False, indent=2), encoding='utf-8')

    def run_case(case):
        local.calls = []
        started = time.perf_counter()
        try:
            if args.service:
                from app.chat_service import run_chat
                from app.models.schemas import ChatRequest
                from app.storage.database import get_repository
                response = run_chat(ChatRequest(message=case['input'], data_source='evaluation'))
                with get_repository().db.connect() as con:
                    events = con.execute("SELECT payload_json FROM events WHERE request_id=? AND event_type='tool_executed' ORDER BY id", (response['request_id'],)).fetchall()
                result = {**response, 'final_response':response['reply'],
                          'tool_results':[{'name':json.loads(e['payload_json'])['name']} for e in events]}
            else:
                result = agent_graph.invoke({'user_message': case['input'], 'messages': [],
                                             'thought_chain': [], 'retrieved_docs': [], 'tool_results': []})
        except Exception as exc:
            result = {'_error': type(exc).__name__, 'final_response': ''}
        return redact({'case_id': case['case_id'], 'split': case['split'], 'category': case['category'],
                       'repeat_index': case['repeat_index'], 'input': case['input'], 'result': result,
                       'score': score(case, result), 'seconds': round(time.perf_counter() - started, 4),
                       'llm_calls': local.calls})

    rows = []
    with (args.output / 'results.jsonl').open('w', encoding='utf-8') as file:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(run_case, case) for case in cases]
            for future in as_completed(futures):
                row = future.result()
                rows.append(row)
                file.write(json.dumps(row, ensure_ascii=False) + '\n')
                file.flush()
                print(f"{len(rows)}/{len(cases)} {row['case_id']} passed={row['score']['passed']} seconds={row['seconds']}", flush=True)

    # Separate same-text complaints represent separate inputs, not persistence.
    ticket_ids = [r['result']['escalation_ticket']['ticket_id'] for r in rows if r['result'].get('escalation_ticket')]
    categories = {}
    for row in rows:
        entry = categories.setdefault(row['category'], {'total': 0, 'passed': 0})
        entry['total'] += 1
        entry['passed'] += int(row['score']['passed'])
    all_calls = [call for row in rows for call in row['llm_calls']]
    summary = {'total': len(rows), 'passed': sum(r['score']['passed'] for r in rows),
               'execution_errors': sum(bool(r['result'].get('_error')) for r in rows),
               'facts_passed': sum(r['score']['facts_passed'] for r in rows),
               'safety_passed': sum(r['score']['safety_passed'] for r in rows),
               'tools_passed': sum(r['score']['tools_passed'] for r in rows),
               'ticket_ids_unique': len(ticket_ids) == len(set(ticket_ids)),
               'ticket_count': len(ticket_ids), 'categories': categories,
               'median_seconds': round(statistics.median(r['seconds'] for r in rows), 4),
               'llm_call_count': len(all_calls),
               'reported_total_tokens': sum((c.get('usage') or {}).get('total_tokens', 0) for c in all_calls),
               'calls_without_usage': sum(not bool(c.get('usage')) for c in all_calls),
               'failed_cases': [r['case_id'] for r in rows if not r['score']['passed']]}
    manifest.update({'finished_at': datetime.now().astimezone().isoformat(),
                     'source_unchanged_during_run': source_manifest(root) == before,
                     'source_after': source_manifest(root)})
    (args.output / 'manifest.json').write_text(json.dumps(redact(manifest), ensure_ascii=False, indent=2), encoding='utf-8')
    (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
