"""Build the reviewed-by-author reference draft from explicitly curated method families.

No model, network, question database or running workspace state is accessed.
Each row is an independently chosen task/structure, never a Cartesian product.
"""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import routine_classification as rc
from backend.routine_matching import CATEGORY_PREFIXES

SOURCE = ROOT / 'backend/routine_expansion'


def build():
    catalog = json.loads((SOURCE / 'base-v1.json').read_text())
    original = deepcopy(catalog)
    by_id = {r['id']: r for r in catalog['routines']}
    next_ids = {prefix: max(int(r['id'].split('-')[1]) for r in catalog['routines']
                           if r['id'].startswith(prefix+'-')) for prefix in CATEGORY_PREFIXES.values()}
    families = []
    for path in sorted(SOURCE.glob('*.txt')):
        family = None
        for lineno, raw in enumerate(path.read_text().splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            parts = [s.strip() for s in line.split('|')]
            if line.startswith('@'):
                parent, method, steps, exclusion = parts
                parent = parent[1:]
                if parent not in by_id:
                    raise ValueError(f'{path}:{lineno}: unknown parent {parent}')
                family = {'parent': parent, 'method': method, 'steps': steps.split('；'),
                          'exclusion': exclusion, 'ids': []}
                families.append(family)
                continue
            if family is None or len(parts) not in (3, 4):
                raise ValueError(f'{path}:{lineno}: expected task|signal|first step[|exclusion]')
            task, signal, first = parts[:3]
            parent = by_id[family['parent']]
            prefix = parent['id'].split('-')[0]
            next_ids[prefix] += 1
            rid = f'{prefix}-{next_ids[prefix]:03d}'
            name = task + '：' + family['method']
            routine = {'id': rid, 'name': name, 'category': parent['category'],
                       'signals': [signal, '解析关键转化：'+first],
                       'retrieval_terms': list(dict.fromkeys([task, family['method'], *task.replace('与','、').split('、')])),
                       'key_steps': [first, *family['steps']],
                       'exclusions': [family['exclusion'], *parts[3:]],
                       'confusable_ids': [family['parent']], 'aliases': []}
            catalog['routines'].append(routine)
            family['ids'].append(rid)
        if family is None:
            raise ValueError(f'empty source: {path}')
    for family in families:
        for i, rid in enumerate(family['ids']):
            routine = next(r for r in catalog['routines'] if r['id'] == rid)
            routine['confusable_ids'] += [r for r in family['ids'][max(0,i-1):i+2] if r != rid][:2]
    refinements = {}
    for family in families:
        refinements.setdefault(family['parent'], []).append(family)
    for parent, children in refinements.items():
        methods = list(dict.fromkeys(f['method'] for f in children))
        by_id[parent]['exclusions'].append('已有专门条目时按题型结构细分：'+ '、'.join(methods)+'；本项仅保留原关键方法适用的一般情形。')
    catalog.update(version='2026-10-24.v2',
                   description='高中主线与压轴拓展的细套路参考目录；新增和修订内容等待人工审核；不代表题目已重分类。',
                   naming_rule='问题目标与题型结构＋关键方法；不同关键转化分开，数值、背景和记号变化不新建。')
    rc.validate_catalog(catalog)
    return catalog, original, families


def render(catalog, original, families):
    counts = Counter(r['category'] for r in catalog['routines'])
    lines = [f'# 套路参考目录（{len(catalog["routines"])}项）', '',
             '新增和修订项为待人工审核参考内容。旧题目分类未重跑；套路内容审核与题目归属审核分开。', '',
             '在「套路图谱 → 目录审核」中编辑完整字段、预览公式、标记状态和导出 JSON。', '',
             '每项按问题目标、题型结构及关键方法区分。仅数字、背景或符号变化不独立建项。', '']
    for category in CATEGORY_PREFIXES:
        lines += [f'## {category}（{counts[category]}项）', '', '| 编号 | 套路 | 识别结构 | 关键步骤 | 排除条件 | 易混淆编号 |', '|---|---|---|---|---|---|']
        for r in catalog['routines']:
            if r['category'] != category:
                continue
            cells = [r['id'], r['name'], '；'.join(r['signals']), ' → '.join(r['key_steps']), '；'.join(r['exclusions']), '、'.join(r['confusable_ids'])]
            lines.append('| ' + ' | '.join(c.replace('|', '\\|').replace('\n', ' ') for c in cells) + ' |')
        lines.append('')
    report = ['# 本轮套路扩充与细化对照', '', f'基础 {len(original["routines"])} 项 → 新目录 {len(catalog["routines"])} 项。所有原编号保留。', '',
              '| 板块 | 原数量 | 新数量 |', '|---|---:|---:|']
    oldcounts = Counter(r['category'] for r in original['routines'])
    for cat, count in counts.items():
        report.append(f'| {cat} | {oldcounts[cat]} | {count} |')
    report += ['', '## 旧条目与细分方法', '', '| 原条目 | 细分路线 | 新编号 |', '|---|---|---|']
    for f in families:
        report.append(f'| {f["parent"]} | {f["method"]} | '+ '、'.join(f['ids'])+' |')
    report += ['', '## 内容依据与审核边界', '',
               '依据现有目录、题库解析中的方法结构和高中常见题型人工编写；不是模型自动批量归类。来源文件每一行都是显式选择的目标、识别结构和第一步转化，不生成章节、曲线和方法的笛卡尔积。', '',
               '历史完成批次有 23,255 题，6,250 题没有主套路，其中包含资料不足与请求失败。新套路草案仅作线索，不直接作为已核验事实。', '',
               '定点核对示例：#14100 用韦达关系推出直线过定点，#14442 用端点参数消元证明弦线定点；旧 GEO-028 不能替代结构明确的细分条目。最值示例：#13109 涉及弦长和面积化斜率平方，#13223 涉及中点约束消元后的斜率分式最值。', '',
               '解析几何极点极线条目由标准二次曲线的双线性切线式建立，分别核对外点实切线、接触弦和退化位置；它们属于压轴拓展，不能把一般动弦当成接触弦。', '',
               '极线与接触弦的概念核对：[Wolfram MathWorld — Polar](https://mathworld.wolfram.com/Polar.html)。抛物线焦准等距、参数形式核对：[Wolfram MathWorld — Parabola](https://mathworld.wolfram.com/Parabola.html)。这些资料只支持相应概念，不代表对全部目录的外部认证。', '',
               '内容完成结构与方法边界复核，但尚待用户逐条审核；公式适用条件、竞合条目及真实分类效果需在后续审核中持续校准。本轮不产生新版题库覆盖率。']
    return '\n'.join(lines), '\n'.join(report)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='compare only; do not write')
    args = parser.parse_args()
    catalog, original, families = build()
    markdown, report = render(catalog, original, families)
    outputs = {ROOT/'backend/routine_catalog.json': json.dumps(catalog, ensure_ascii=False, indent=2)+'\n',
               ROOT/'docs/routine-catalog.md': markdown,
               ROOT/'docs/routine-expansion.md': report}
    if args.check:
        if any(not p.exists() or p.read_text() != text for p, text in outputs.items()):
            raise SystemExit('generated catalogue/docs differ; run build_routine_catalog.py')
    else:
        for p, text in outputs.items():
            p.write_text(text)
    print(json.dumps({'total': len(catalog['routines']), 'categories': dict(Counter(r['category'] for r in catalog['routines']))}, ensure_ascii=False))


if __name__ == '__main__':
    main()
