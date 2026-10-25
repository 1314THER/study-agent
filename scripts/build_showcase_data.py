"""Build national-paper assets from saved production runs, never owner DBs.

Student responses and teaching scripts below are explicitly schematic. Actual
model comparisons and teaching transitions live separately in recordings.json.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.demo_presets import get_preset
from backend.geometry import compile_geometry, fingerprint
from scripts.build_showcase_bank import public_answer

NATIONAL_IDS = ('national-2023-q17', 'national-2025-q16')


def recorded_examples():
    runs = json.loads((ROOT/'frontend/showcase/pipeline.json').read_text())['examples']
    examples = []
    for identifier in NATIONAL_IDS:
        item = get_preset(identifier)
        record = runs[identifier]['xuefeng']
        item['answer_json'] = deepcopy(record['answer_json'])
        item['prepared_example'] = False
        item['recording'] = {'run_at': record['run_at'], 'fingerprint': record['fingerprint'],
                             'teacher': 'xuefeng', 'kind': 'saved_production_pipeline',
                             'model': record['stages']['solver']['model'],
                             'reasoning_effort': record['stages']['solver'].get('reasoning_effort')}
        examples.append(item)
    return examples


def triangle_geometry(example):
    """Exact triangle diagram derived from the national paper's checked answer."""
    answer = deepcopy(example['answer_json'])
    objects = [{'id': name, 'kind': 'point', 'coords': coords, 'label': name, 'base': True}
               for name, coords in [('A', [0, 0]), ('B', [5, 0]), ('C', [2, 6])]]
    objects.extend([
        {'id': 'AB', 'kind': 'segment', 'a': 'A', 'b': 'B', 'base': True},
        {'id': 'BC', 'kind': 'segment', 'a': 'B', 'b': 'C', 'base': True},
        {'id': 'CA', 'kind': 'segment', 'a': 'C', 'b': 'A', 'base': True},
        {'id': 'D', 'kind': 'point', 'coords': [2, 0], 'label': 'D'},
        {'id': 'CD', 'kind': 'segment', 'a': 'C', 'b': 'D', 'dashed': True},
    ])
    steps = []
    for chunk in answer['chunk_results']:
        for step in chunk['steps']:
            visible = ['D', 'CD'] if chunk['chunk_id'] == 2 else []
            steps.append({'step_key': f"{chunk['chunk_id']}-{step['step_number']}", 'scene_id': 'main',
                          'full_visible': visible,
                          'hint_groups': ([{'text': '作 CD 垂直于 AB，由边角关系得到高 CD=6。',
                                            'visible': visible}] if visible else [])})
    raw = {'scenes': [{'id': 'main', 'dimension': 2, 'title': '全国Ⅰ卷：三角形与边上的高',
                       'bounds': [-1, 7, 6, -1], 'objects': objects, 'constraints': [
                           {'kind': 'distance', 'a': 'A', 'b': 'B', 'value': 5, 'source': example['question']},
                           {'kind': 'distance', 'a': 'A', 'b': 'C', 'value': '2*sqrt(10)', 'source': example['question']},
                           {'kind': 'perpendicular', 'a': 'C', 'b': 'D', 'c': 'A', 'd': 'B', 'source': example['question']},
                           {'kind': 'on_line', 'a': 'A', 'b': 'B', 'point': 'D', 'source': example['question']},
                       ]}], 'steps': steps}
    geometry = compile_geometry(raw, example['question'], answer)
    if geometry['status'] != 'ready' or geometry.get('issues'):
        raise ValueError(f"全国卷几何构造未通过校验：{geometry.get('issues')}")
    geometry['source_hash'] = fingerprint(example['question'], answer)
    answer['geometry'] = geometry
    return {'id': 'national-triangle-height', 'label': '2023 年新课标全国Ⅰ卷第17题 · 辅助线',
            'question': example['question'], 'answer_json': answer,
            'source': '全国卷真实题；图形由已保存解答构造，坐标与辅助线经确定性检查。不是学生笔迹或模型生成记录。',
            'source_meta': deepcopy(example['source']), 'prepared_diagram': True}


def teaching_example(example):
    return {'label': '2023 年新课标全国Ⅰ卷第17题 · 方案说明', 'source': deepcopy(example['source']),
            'prepared_example': True,
            'label_note': '人工编排的数学教学示意，不是真实学生记录或 AI 实时回答；真实教学记录另列。',
            'question': example['question'], 'steps': [
                {'title': '用三角形内角和确定 C',
                 'standard_writing': r'$A+B+C=\pi$ 且 $A+B=3C$，所以 $4C=\pi$，$C=\frac\pi4$。',
                 'prompt': '将题设的角关系与三角形内角和放在一起，C 等于多少？',
                 'hints': [r'把 $A+B$ 替换成 $3C$。', r'$3C+C=\pi$。'],
                 'wrong_answer': r'$C=\frac\pi3$', 'right_answer': r'$C=\frac\pi4$',
                 'wrong_feedback': '这里遗漏了内角和中的 C；应为 4C=π。尚不能由这一处错误判断知识是否掌握。',
                 'right_feedback': '角 C 已确定。接下来处理三角恒等变换。'},
                {'title': '展开两角和差，求出 sin A',
                 'standard_writing': r'$2\sin(A-C)=\sin(A+C)$，展开并代入 $C=\frac\pi4$，得 $\sin A=3\cos A$，故 $\sin A=\frac{3\sqrt{10}}{10}$。',
                 'prompt': '把 sin B 改写为 sin(A+C)，再展开等式两边。',
                 'hints': [r'$B=\pi-(A+C)$，因此 $\sin B=\sin(A+C)$。', '分别使用正弦的两角和、两角差公式。'],
                 'wrong_answer': r'$\sin A=\cos A$', 'right_answer': r'$\sin A=\frac{3\sqrt{10}}{10}$',
                 'wrong_feedback': '检查展开式中的系数与符号；原因仍需结合写出的等式确认。',
                 'right_feedback': '这里既需要公式，也需要角的范围确定符号。'},
                {'title': '由正弦定理求边，再求高',
                 'standard_writing': r'$\sin B=\frac{2\sqrt5}{5}$，由正弦定理 $AC=2\sqrt{10}$，所以 $h=AC\sin A=6$。',
                 'prompt': '已知 AB=5，怎样用正弦定理把所求高与已知边角联系起来？',
                 'hints': [r'$\frac{AC}{\sin B}=\frac{AB}{\sin C}$。', r'作 $CD\perp AB$，有 $CD=AC\sin A$。'],
                 'wrong_answer': r'$h=5\sin A$', 'right_answer': '$h=6$',
                 'wrong_feedback': 'AB 是底边，不是含角 A 的直角三角形中的斜边；先核对边角对应。',
                 'right_feedback': '完整题目完成后，还需用新题独立检查这一方法。'},
            ], 'variant': {
                'prepared_example': True, 'source': '由全国Ⅰ卷第17题改编的原创数学示例；不是模型生成结果',
                'reference_id': example['id'],
                'question': r'【原创变式】保留原题的角关系，将 $AB=5$ 改为 $AB=10$，求 $AB$ 边上的高。',
                'method': '角关系不变，先求角与正弦，再由正弦定理及辅助线求高。',
                'solution': r'角保持不变，对应边长扩大为原来的两倍，高也扩大两倍，故 $h=12$。', 'answer': '$12$'}}


def build():
    examples = recorded_examples()
    primary = examples[0]
    catalog = json.loads((ROOT/'backend/routine_catalog.json').read_text())
    known = {row['id'] for row in catalog['routines']}
    if any(other not in known for row in catalog['routines'] for other in row['confusable_ids']):
        raise ValueError('套路目录引用不完整')
    geometry = triangle_geometry(primary)
    rows = [{'id': e['id'], 'label': e['label'], 'question': e['question'], 'source': deepcopy(e['source']),
             'answer': e['answer_json']['final_answer'], 'category': e['answer_json']['chunk_results'][0]['category']['level1'],
             'prepared_example': False, 'difficulty_label': '已保存管线评分，非经校准量表'} for e in examples]
    return {'schema_version': 2, 'prepared_examples': False, 'examples': examples,
            'diagnosis': {
                'label': '2023 年新课标全国Ⅰ卷第17题 · 构造错答', 'source': deepcopy(primary['source']),
                'question': primary['question'], 'prepared_example': True,
                'student_label': '人工构造的诊断输入，不是真实学生记录或模型批改结果',
                'lines': [{'title': '合并角关系', 'writing': r'$A+B=3C$，因此 $3C=\pi$。'},
                          {'title': '确定角', 'writing': r'$C=\frac\pi3$。'},
                          {'title': '沿用错误前提', 'writing': r'把 $C=\frac\pi3$ 代入后续两角和差式。'}],
                'first_error': 0, 'error_type': '最早可观察错误：内角和漏项',
                'explanation': '三角形内角和应包含 C，第一行应为 4C=π。后续沿用该值的影响应与新的独立错误分开核对。',
                'evidence': r'$A+B+C=\pi$ 与 $A+B=3C$ 联立，得 $4C=\pi$，故 $C=\frac\pi4$。',
                'feedback': '先确认第一行如何得到；这份作答不足以直接判断全部三角函数知识的掌握程度。',
                'corrected_steps': deepcopy(primary['answer_json']['chunk_results'][0]['steps'])},
            'geometry': geometry, 'geometry_examples': [deepcopy(geometry)],
            'teaching': teaching_example(primary), 'pool_examples': [],
            'library': {'title': '全国卷研究展示样例', 'items': rows,
                        'question_ids': [e['id'] for e in rows], 'calendar': [],
                        'note': '仅含两道有保存管线结果的全国卷题；非完整全国卷题库。组卷与打印由当前所选题生成。'},
            'progress': {'as_of': datetime.now().astimezone().date().isoformat(), 'scope': '全国卷公开案例', 'published_questions': 2,
                         'completed_pipeline_runs': 8,
                         'note': '两道题各保留四份已保存的真实管线结果；数量不是诊断准确率或学习效果。'},
            'catalog': catalog}


def write_national_bank(examples, destination):
    """Publish only the two verified source-tagged national examples."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    index, details, sources = [], {}, []
    for item, qid in zip(examples, (20230117, 20250116)):
        source = {'id': len(sources)+1, 'name': item['source']['paper'], 'url': item['source']['url']}
        sources.append(source)
        answer = public_answer(item['answer_json'])
        category = item['answer_json']['chunk_results'][0]['category']['level1']
        origin = {**source, 'question_no': str(item['source']['question_number']),
                  'page_start': None, 'page_end': None, 'images': []}
        detail = {'id': qid, 'question': item['question'], 'answer': answer['final_answer'], 'solution': '',
                  'answer_json': answer, 'categories': [category], 'type': '大题',
                  'year': str(item['source']['year']), 'region': '全国卷', 'difficulty': '管线实例评分',
                  'completeness': 'complete', 'sources': [origin], 'method': '', 'match': {}}
        details[str(qid)] = detail
        index.append({**{key: detail[key] for key in ('id', 'question', 'categories', 'type', 'year', 'region', 'difficulty', 'completeness')},
                      'source_ids': [source['id']], 'has_answer': True, 'has_images': False, 'routine': None})
    files = {}
    for name, value in [('index.json', index), ('part-0000.json', details)]:
        path = destination/name
        path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':'))+'\n')
        files[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size}
    manifest = {'version': 1, 'count': len(index), 'page_size': 100, 'sources': sources,
                'categories': sorted({c for row in index for c in row['categories']}),
                'years': sorted({row['year'] for row in index}, reverse=True), 'types': ['大题'], 'routines': {},
                'parts': {str(row['id']): 'part-0000.json' for row in index}, 'files': files}
    (destination/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, separators=(',', ':'))+'\n')


if __name__ == '__main__':
    result = build()
    destination = ROOT/'frontend/showcase/data.json'
    destination.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'))+'\n')
    write_national_bank(result['examples'], destination.parent/'question-bank')
    print('已构建两道全国卷案例及公开题库；未读取私人数据库，未调用模型。')
