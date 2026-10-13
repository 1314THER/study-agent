"""Run the production solver/verifier/formatter for the public exam examples.

Provider responses stay in the ignored build directory. Only public questions,
finished answers and the three stage outputs are exported for the demo website.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import settings, solver
from backend.demo_presets import get_preset, public_presets

TEACHERS = ('liangliang', 'taotao', 'xuefeng', 'ji')
CACHE = ROOT / '.runtime/showcase-pipeline'
CONTEXT = threading.local()
REAL_CALL = solver.call_deepseek


def checksum(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def traced_call(*args, **kwargs):
    began = time.monotonic()
    content, usage = REAL_CALL(*args, **kwargs)
    prompt = args[0]
    stage = 'formatter' if prompt.startswith(solver.FORMATTER_PROMPT) else 'solver' if prompt.startswith(solver.SOLVER_PROMPT) else 'geometry' if prompt.startswith((ROOT / 'backend/prompts/geometry.md').read_text().strip()) else 'verifier'
    CONTEXT.calls.append({'stage': stage, 'model': kwargs.get('model', 'deepseek-flash'),
                          'reasoning_effort': kwargs.get('reasoning_effort'), 'usage': usage,
                          'seconds': round(time.monotonic() - began, 2), 'content': content})
    return content, usage


def run_one(example, teacher, rerun=False):
    preset = get_preset(example['id'])
    prompt_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (ROOT / 'backend/prompts').rglob('*.md')}
    fingerprint = checksum({'question': preset['question'], 'teacher': teacher,
                            'config': settings.get_teacher_config(teacher), 'prompts': prompt_hashes,
                            'solver': hashlib.sha256((ROOT / 'backend/solver.py').read_bytes()).hexdigest()})
    directory = CACHE / preset['id'] / teacher
    directory.mkdir(parents=True, exist_ok=True)
    final_path = directory / 'result.json'
    if not rerun and final_path.is_file():
        cached = json.loads(final_path.read_text())
        if cached.get('fingerprint') == fingerprint and not cached['answer_json'].get('error'):
            print(f"{preset['id']} / {teacher}: cached completed run", flush=True)
            return preset['id'], teacher, cached
    CONTEXT.calls = []
    usage = dict.fromkeys(('prompt_tokens', 'completion_tokens', 'total_tokens'), 0)
    question = preset['question']
    began = time.monotonic()
    for stage in ('solver', 'verifier', 'formatter'):
        CONTEXT.stage = stage
        print(f"{preset['id']} / {teacher}: {stage}", flush=True)
        if stage == 'solver':
            solved = solver.step_solver_only(question, teacher=teacher)
            if solved.get('error'):
                raise RuntimeError(solved.get('detail') or solved['error'])
            value = solved
        elif stage == 'verifier':
            verified = solver.step_verify_all(solved['content'], question, solved.get('category'), teacher=teacher)
            value = verified
        else:
            value = solver.step_final_check(question, verified['chunk_results'], [], usage, teacher=teacher,
                                           solver_content=solved['content'], verifier_category=solved.get('category'))
        if stage != 'formatter':
            for field in usage:
                usage[field] += (value.get('token_usage') or {}).get(field, 0)
        (directory / (stage + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        (directory / 'calls.json').write_text(json.dumps(CONTEXT.calls, ensure_ascii=False, indent=2) + '\n')
    if value.get('error') or value.get('formatter_fallback'):
        raise RuntimeError(value.get('formatter_note') or value.get('error') or 'Incomplete formatter')
    if not solver._is_well_formed_chunk_results(value.get('chunk_results')):
        raise RuntimeError('Incomplete steps')
    value.update(source='pipeline', prepared_example=False, teacher=teacher)
    result = {'fingerprint': fingerprint, 'run_at': datetime.now().astimezone().isoformat(),
              'seconds': round(time.monotonic() - began, 2), 'answer_json': value,
              'stages': {stage: next(call for call in reversed(CONTEXT.calls) if call['stage'] == stage)
                         for stage in ('solver', 'verifier', 'formatter')}}
    final_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f"{preset['id']} / {teacher}: done, {value['token_usage']['total_tokens']} tokens", flush=True)
    return preset['id'], teacher, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=4)
    parser.add_argument('--rerun', action='store_true')
    parser.add_argument('--example', choices=[example['id'] for example in public_presets()])
    parser.add_argument('--teacher', choices=TEACHERS)
    args = parser.parse_args()
    if not settings.get_api_key('deepseek'):
        raise SystemExit('请先配置本机 DeepSeek API。')
    CACHE.mkdir(parents=True, exist_ok=True, mode=0o700)
    solver.call_deepseek = traced_call
    output = {'version': 1, 'examples': {}}
    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks = {pool.submit(run_one, example, teacher, args.rerun): (example['id'], teacher)
                 for example in public_presets() if not args.example or example['id'] == args.example
                 for teacher in TEACHERS if not args.teacher or teacher == args.teacher}
        for task in as_completed(tasks):
            try:
                example_id, teacher, result = task.result()
                output['examples'].setdefault(example_id, {})[teacher] = result
            except Exception as error:
                example_id, teacher = tasks[task]
                failures.append({'example': example_id, 'teacher': teacher, 'error': str(error)[:300]})
                print(f'{example_id} / {teacher}: failed ({type(error).__name__})', flush=True)
    # Keep completed runs from the other examples; each retains its original
    # timestamp and fingerprint rather than pretending it ran again.
    for example in public_presets():
        for teacher in TEACHERS:
            path = CACHE / example['id'] / teacher / 'result.json'
            if teacher not in output['examples'].get(example['id'], {}) and path.is_file():
                value = json.loads(path.read_text())
                calls = json.loads((path.parent / 'calls.json').read_text())
                for call in reversed(calls):
                    try:
                        structured = json.loads(solver._extract_json(call['content']))
                    except ValueError:
                        continue
                    if isinstance(structured, dict) and structured.get('chunk_results'):
                        value['stages']['formatter'] = {**call, 'stage': 'formatter'}
                        break
                output['examples'].setdefault(example['id'], {})[teacher] = value
    (CACHE / 'run-summary.json').write_text(json.dumps({'completed': sum(map(len, output['examples'].values())),
                                                       'failed': failures}, ensure_ascii=False, indent=2) + '\n')
    if failures or sum(map(len, output['examples'].values())) != 12:
        raise SystemExit(f'{len(failures)} runs failed; check .runtime/showcase-pipeline/run-summary.json')
    destination = ROOT / 'frontend/showcase/pipeline.json'
    destination.write_text(json.dumps(output, ensure_ascii=False, separators=(',', ':')) + '\n')
    print('Completed 12 production pipeline runs.', flush=True)


if __name__ == '__main__':
    main()
