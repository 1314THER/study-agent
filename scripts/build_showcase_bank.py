"""Export question content and explanations from the existing small library.

Study records, account IDs, private metadata and provider settings are excluded.
"""
from contextlib import closing
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
IMAGE = re.compile(r'^[0-9a-f]{64}\.png$')


def load(value, default=None):
    try:
        return json.loads(value) if value else default
    except (ValueError, TypeError):
        return default


def public_answer(answer):
    result = {key: answer[key] for key in ('status', 'final_answer', 'overall_difficulty', 'knowledge_points') if key in answer}
    result['chunk_results'] = []
    for chunk in answer.get('chunk_results') or []:
        item = {key: chunk[key] for key in ('chunk_id', 'chunk_type', 'category', 'difficulty', 'knowledge_points', 'final_answer') if key in chunk}
        item['steps'] = [{key: step[key] for key in ('step_number', 'title', 'step_level1', 'standard_writing', 'detailed_writing', 'knowledge_point', 'step_difficulty') if key in step} for step in chunk.get('steps') or []]
        result['chunk_results'].append(item)
    return result


def build(database, destination, assets):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    index, files, details, sources, image_refs = [], {}, {}, {}, set()
    def write(name, value):
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')
        files[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size}
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        for row in db.execute('SELECT id,content,answer_json,category_level1,question_type,source_type,source_meta,difficulty_level FROM questions ORDER BY id'):
            answer = load(row['answer_json'], {})
            metadata = load(row['source_meta'], {})
            source_name = str(metadata.get('paper') or row['source_type'] or '题库')
            if source_name not in sources:
                sources[source_name] = {'id': len(sources) + 1, 'name': source_name, 'url': ''}
            origin = {**sources[source_name], 'question_no': str(metadata.get('question_no') or ''), 'page_start': None, 'page_end': None, 'images': []}
            for ref in answer.get('asset_refs') or []:
                path = Path(assets) / str(ref)
                if isinstance(ref, str) and IMAGE.fullmatch(ref) and path.is_file():
                    origin['images'].append({'ref': ref, 'label': '题图'})
                    image_refs.add(ref)
            year = re.search(r'(20\d{2})', source_name)
            item = {'id': row['id'], 'question': row['content'], 'answer': answer.get('final_answer') or '',
                    'solution': '', 'answer_json': public_answer(answer), 'categories': [row['category_level1']] if row['category_level1'] else [],
                    'type': row['question_type'] or '未知', 'year': year.group(1) if year else '', 'region': '',
                    'difficulty': row['difficulty_level'] or '未知', 'completeness': 'complete', 'sources': [origin],
                    'method': str(metadata.get('pattern') or ''), 'match': {}}
            index.append({key: item[key] for key in ('id', 'question', 'categories', 'type', 'year', 'region', 'difficulty', 'completeness')})
            index[-1].update(source_ids=[origin['id']], has_answer=bool(item['answer']), has_images=bool(origin['images']), routine=None)
            details[row['id']] = item
    for offset in range(0, len(index), 100):
        write(f'part-{offset // 100:04d}.json', {str(row['id']): details[row['id']] for row in index[offset:offset + 100]})
    for ref in sorted(image_refs):
        source = Path(assets) / ref
        assert hashlib.sha256(source.read_bytes()).hexdigest() + '.png' == ref, '题图校验失败'
        name = 'images/' + ref
        target = destination / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, target)
        files[name] = {'sha256': ref[:-4], 'size': target.stat().st_size}
    write('index.json', index)
    manifest = {'version': 1, 'count': len(index), 'page_size': 100, 'sources': list(sources.values()),
                'categories': sorted({c for row in index for c in row['categories']}),
                'years': sorted({row['year'] for row in index if row['year']}, reverse=True),
                'types': sorted({row['type'] for row in index}), 'routines': {},
                'parts': {str(row['id']): f'part-{position // 100:04d}.json' for position, row in enumerate(index)}, 'files': files}
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, separators=(',', ':')) + '\n')
    return {'questions': len(index), 'sources': len(sources), 'images': len(image_refs),
            'size_mib': round(sum(p.stat().st_size for p in destination.rglob('*') if p.is_file()) / 1048576, 2)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, default=ROOT / 'study_agent.db')
    parser.add_argument('--assets', type=Path, default=ROOT / '.runtime/question-assets')
    parser.add_argument('--destination', type=Path, default=ROOT / 'frontend/showcase/question-bank')
    args = parser.parse_args()
    print(json.dumps(build(args.database, args.destination, args.assets), ensure_ascii=False))
