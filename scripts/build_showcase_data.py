"""Build public, fixed demonstration assets without reading owner databases."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.demo_presets import get_preset, public_presets
from backend.geometry import compile_geometry, fingerprint


def section_example():
    question = '正方体棱长为 2，作平行于底面的截面，观察截面位置改变时的几何关系。'
    vertices = [('A',[0,0,0]),('B',[2,0,0]),('C',[2,2,0]),('D',[0,2,0]),
                ('U',[0,0,2]),('V',[2,0,2]),('W',[2,2,2]),('X',[0,2,2])]
    objects = [{'id':name,'kind':'point','coords':coords,'label':name,'base':True} for name,coords in vertices]
    objects.append({'id':'cube','kind':'solid','faces':[['A','B','C','D'],['U','V','W','X'],['A','B','V','U'],['B','C','W','V'],['C','D','X','W'],['D','A','U','X']], 'base':True})
    for name,xy in [('E',[0,0]),('F',[2,0]),('G',[2,2]),('H',[0,2])]:
        objects.append({'id':name,'kind':'point','coords':xy+['t'],'label':name})
    objects.append({'id':'section','kind':'plane','points':['E','F','G','H']})
    steps = [
        {'step_number':1,'title':'确定截面上的四个点','standard_writing':'在四条竖直棱上，分别取距底面高度为 $t$ 的点 $E,F,G,H$，其中 $0<t<2$。', 'detailed_writing':'四个点处于同一高度，因此在一个平行于底面的平面内。'},
        {'step_number':2,'title':'连接并观察平行截面','standard_writing':'连接 $E,F,G,H$，得到边长为 $2$ 的正方形截面。改变 $t$，截面沿竖直方向移动，面积保持为 $4$。','detailed_writing':'截面边分别平行于底面对应的边。高度改变不影响水平边长，因此截面的形状和面积保持不变。'},
    ]
    answer = {'prepared_example':True,'source_label':'自拟几何构造示例','chunk_results':[{'chunk_id':1,'steps':steps}]}
    raw = {'scenes':[{'id':'main','dimension':3,'title':'正方体的平行截面','objects':objects,
        'parameter':{'name':'t','min':.1,'max':1.9,'value':1},
        'constraints':[{'kind':'distance','a':'A','b':'B','value':2,'source':question},
                       {'kind':'parallel','a':'E','b':'F','c':'A','d':'B','source':question}]}],
        'steps':[{'step_key':'1-1','scene_id':'main','full_visible':['E','F','G','H'],
                  'hint_groups':[{'text':'在四条竖直棱上取同一高度的点。','visible':['E','F','G','H']}]},
                 {'step_key':'1-2','scene_id':'main','full_visible':['E','F','G','H','section'],
                  'hint_groups':[{'text':'连接四点得到平行于底面的正方形截面；拖动参数可观察位置变化。','visible':['section']}]}]}
    geometry = compile_geometry(raw, question, answer)
    if geometry['status'] != 'ready' or geometry.get('issues'):
        raise ValueError('展示几何构造未通过校验')
    geometry['source_hash'] = fingerprint(question, answer)
    answer['geometry'] = geometry
    return {'question':question,'answer_json':answer,'source':'项目自拟构造示例；场景参数与已声明几何关系已校验。'}


def build():
    catalog = json.loads((ROOT/'backend/routine_catalog.json').read_text())
    known = {r['id'] for r in catalog['routines']}
    if any(other not in known for r in catalog['routines'] for other in r['confusable_ids']):
        raise ValueError('套路目录引用不完整')
    shanghai = get_preset('shanghai-2024-q18')
    return {'schema_version':1,'prepared_examples':True,
        'examples':[get_preset(p['id']) for p in public_presets()],
        'diagnosis':{'label':'2024 上海卷第 18 题 · 第 (1) 问','source':deepcopy(shanghai['source']),
            'question':shanghai['question'].split('\n(2)')[0],
            'student_label':'为演示预制的学生作答，不是真实学生记录',
            'lines':[{'title':'确定底数','writing':'由 $\\log_a 4=2$ 且 $a>0$，得到 $a=2$。'},
                     {'title':'利用递增性','writing':'$\\log_2(2x-2)<\\log_2 x$，于是 $2x-2<x$，得到 $x<2$。'},
                     {'title':'写出解集','writing':'所以解集为 $(-\\infty,2)$。'}],
            'first_error':1,'error_type':'条件遗漏 · 对数真数的定义域',
            'explanation':'比较真数前，需要先保证两个对数都有意义。递增性推得 x<2 这个条件本身正确，错误在于遗漏了定义域条件，并把它直接当作最终解集。',
            'evidence':'$2x-2>0$ 且 $x>0$，所以 $x>1$；与 $x<2$ 取交集，得到 $(1,2)$。',
            'feedback':'先写出定义域，再使用单调性，最后求交集。一次失误是当前作答的证据，不直接等同于没有掌握整个知识点。',
            'corrected_steps':deepcopy(shanghai['answer_json']['chunk_results'][0]['steps'])},
        'geometry':section_example(),'catalog':catalog}


if __name__ == '__main__':
    destination = ROOT/'frontend/showcase/data.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    result = build()
    destination.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
    print(f"展示样例已生成：{len(result['examples'])} 道预制题，{len(result['catalog']['routines'])} 个参考套路；未读取私人数据库。")
