"""Build public, fixed demonstration assets without reading owner databases."""
from copy import deepcopy
import json
from pathlib import Path
import math
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
    final_answer='截面为边长 $2$ 的正方形，面积恒为 $4$；改变 $t$ 只改变位置。'
    answer = {'prepared_example':True,'source_label':'自拟几何构造示例','final_answer':final_answer,
              'chunk_results':[{'chunk_id':1,'category':{'level1':'立体几何'},'steps':steps,'final_answer':final_answer}]}
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
    return {'id':'cube-section','label':'正方体 · 平行截面的参数动画','question':question,'answer_json':answer,
            'source':'项目自拟构造示例；场景参数与已声明几何关系已校验。'}


def _point(name, coordinates, *, base=True):
    return {'id':name,'kind':'point','coords':coordinates,'label':name,'base':base}


def _step(number, title, writing, detail, knowledge):
    return {'step_number':number,'title':title,'standard_writing':writing,'detailed_writing':detail,
            'step_prompt':'请完成本步推理，再看对应辅助构造。','step_answer':writing,
            'knowledge_point':knowledge,'step_level1':'建立几何关系',
            'step_difficulty':{'level':'中等','score':3,'dimensions':{
                '非常规程度':0,'计算量':1,'分类讨论':0,'知识广度':1,'条件转化难度':1}}}


def _geometry_answer(question, category, steps, final_answer, raw):
    result = {'prepared_example':True,'source_type':'项目自拟题','source_label':'人工编排的演示解析',
              'question':question,'final_answer':final_answer,
              'chunk_results':[{'chunk_id':1,'category':{'level1':category},'steps':steps,'final_answer':final_answer}]}
    geometry=compile_geometry(raw,question,result)
    if geometry['status']!='ready' or geometry.get('issues'):
        raise ValueError(f"展示几何构造未通过校验：{geometry.get('issues')}")
    geometry['source_hash']=fingerprint(question,result)
    result['geometry']=geometry
    return result


def ellipse_example():
    # Retain the checked model from tests/geometry_cases.py, with an explicitly
    # self-authored teaching statement. This is not an imported corpus record.
    question=r'【项目自拟教学样例】椭圆 $C:\frac{x^2}{5}+y^2=1$ 的焦点为 $F_1,F_2$。点 $P$ 在椭圆上，且 $PF_1\perp PF_2$。求 $|PF_1|\cdot|PF_2|$。'
    steps=[
        _step(1,'连接第一条焦半径',r'由 $a^2=5,b^2=1$，得 $c=2$，所以 $|F_1F_2|=4$。连接 $PF_1$。',
              r'读出长半轴与短半轴，先确定焦距。画板选取满足题设的一种位置；不把所画的 $P$ 坐标当作额外条件。','椭圆的标准方程'),
        _step(2,'连接第二条焦半径，识别直角三角形',r'连接 $PF_2$。由题设 $PF_1\perp PF_2$，在 $\triangle F_1PF_2$ 中有 $|PF_1|^2+|PF_2|^2=16$。',
              r'第二条辅助线出现后，题设的垂直条件成为直角三角形中的勾股关系；焦点连线是斜边。','勾股定理'),
        _step(3,'把焦半径和转成乘积',r'由椭圆定义，$|PF_1|+|PF_2|=2\sqrt5$。故 $2|PF_1|\cdot|PF_2|=(2\sqrt5)^2-16=4$，乘积为 $2$。',
              r'记两条焦半径为 $u,v$。用 $(u+v)^2=u^2+v^2+2uv$，将定义给出的长度和与上一步的平方和联立。','椭圆的定义'),
    ]
    objects=[_point('F1',[-2,0]),_point('F2',[2,0]),_point('P',['sqrt(15)/2',.5]),
             {'id':'ellipse','kind':'conic','coefficients':[.2,0,1,0,0,-1],'base':True},
             {'id':'PF1','kind':'segment','a':'P','b':'F1'},
             {'id':'PF2','kind':'segment','a':'P','b':'F2'},
             {'id':'focus-gap','kind':'segment','a':'F1','b':'F2','dashed':True}]
    raw={'scenes':[{'id':'main','dimension':2,'title':'椭圆焦半径','bounds':[-3,1.8,3,-1.8],
                   'objects':objects,'constraints':[
                       {'kind':'on_conic','point':'P','conic':'ellipse','source':question},
                       {'kind':'perpendicular','a':'P','b':'F1','c':'P','d':'F2','source':question},
                       {'kind':'length_sum','pairs':[['P','F1'],['P','F2']],'value':'2*sqrt(5)',
                        'source':'$|PF_1|+|PF_2|=2\\sqrt5$'}]}],
         'steps':[
             {'step_key':'1-1','scene_id':'main','full_visible':['PF1','focus-gap'],
              'hint_groups':[{'text':'先观察焦距，再连接第一条焦半径 PF₁。','visible':['focus-gap','PF1']}]},
             {'step_key':'1-2','scene_id':'main','full_visible':['PF1','PF2','focus-gap'],
              'hint_groups':[{'text':'连接 PF₂，利用题设识别以焦距为斜边的直角三角形。','visible':['PF2'],'highlight':['PF1','PF2']}]},
             {'step_key':'1-3','scene_id':'main','full_visible':['PF1','PF2','focus-gap'],
              'hint_groups':[{'text':'对照两条焦半径，用长度和与平方和求乘积。','visible':['PF1','PF2'],'highlight':['PF1','PF2']}]},
         ]}
    answer=_geometry_answer(question,'解析几何',steps,r'$|PF_1|\cdot|PF_2|=2$',raw)
    return {'id':'ellipse-focus','label':'椭圆 · 焦半径的逐步辅助线','question':question,'answer_json':answer,
            'image_url':'/showcase/assets/ellipse-question.svg','image_label':'自拟题面与原始题设图',
            'source':'项目自拟教学样例；复用已校验的椭圆构型。画板只选取满足条件的一种位置。'}


def pyramid_example():
    question=r'【项目自拟教学样例】在三棱锥 $P-ABC$ 中，$\triangle ABC$ 是边长为 $2$ 的等边三角形，$PA=PB=2$，$PC=\sqrt6$。求三棱锥的体积。'
    steps=[
        _step(1,'取中点，作等腰三角形的高',r'取 $AB$ 中点 $E$，连接 $PE$。由 $PA=PB=2$，得 $PE\perp AB$，且 $PE=\sqrt{2^2-1^2}=\sqrt3$。',
              r'等腰三角形的顶点与底边中点连线既是中线也是高。先引入 $E$ 和 $PE$，只使用 $PAB$ 内的已知关系。','等腰三角形'),
        _step(2,'连接底面的中线',r'连接 $CE$。由等边三角形 $ABC$，得 $CE\perp AB$，且 $CE=\sqrt3$。',
              r'底面三角形的中线也是高。此时已得到两条分别位于侧面和底面中的垂线，还不能直接把 $PE$ 当作棱锥的高。','等边三角形'),
        _step(3,'由勾股逆定理确认棱锥的高',r'由 $PC^2=6=PE^2+CE^2$，得 $PE\perp CE$。又 $AB\cap CE=\{E\}$，故 $PE\perp$ 平面 $ABC$。',
              r'利用 $PC$ 的已知长度建立侧面 $PCE$ 中的直角关系。$PE$ 同时垂直于底面内两条相交直线，才可作为棱锥的高。','线面垂直'),
        _step(4,'计算底面积与体积',r'$S_{ABC}=\frac12\cdot AB\cdot CE=\sqrt3$。因此 $V=\frac13S_{ABC}\cdot PE=\frac13\cdot\sqrt3\cdot\sqrt3=1$。',
              r'底面积使用 $AB=2$ 与底面高 $CE$。体积公式中的高使用上一步已经证明垂直于底面的 $PE$。','棱锥体积'),
    ]
    objects=[_point('A',[-1,0,0]),_point('B',[1,0,0]),_point('C',[0,'sqrt(3)',0]),_point('P',[0,0,'sqrt(3)']),
             {'id':'pyramid','kind':'solid','faces':[['A','B','C'],['A','B','P'],['A','C','P'],['B','C','P']],'base':True},
             {'id':'E','kind':'point','construct':{'kind':'midpoint','a':'A','b':'B'},'label':'E'},
             {'id':'PE','kind':'segment','a':'P','b':'E','dashed':True},
             {'id':'CE','kind':'segment','a':'C','b':'E','dashed':True},
             {'id':'base-area','kind':'plane','points':['A','B','C']}]
    constraints=[{'kind':'distance','a':a,'b':b,'value':length,'source':question} for a,b,length in
                 [('A','B',2),('A','C',2),('B','C',2),('P','A',2),('P','B',2),('P','C','sqrt(6)')]]
    constraints.extend([
        {'kind':'perpendicular','a':'P','b':'E','c':'A','d':'B','source':'$PE\\perp AB$'},
        {'kind':'perpendicular','a':'C','b':'E','c':'A','d':'B','source':'$CE\\perp AB$'},
        {'kind':'perpendicular','a':'P','b':'E','c':'C','d':'E','source':'$PE\\perp CE$'},
        {'kind':'on_line','a':'A','b':'B','point':'E','source':'取 $AB$ 中点 $E$'},
    ])
    raw={'scenes':[{'id':'main','dimension':3,'title':'三棱锥的中点与垂线','objects':objects,'constraints':constraints}],
         'steps':[
             {'step_key':'1-1','scene_id':'main','full_visible':['E','PE'],
              'hint_groups':[{'text':'先取 AB 的中点 E。','visible':['E']},
                             {'text':'再连接 PE，利用 PA=PB 得到 PE⊥AB。','visible':['PE']}]},
             {'step_key':'1-2','scene_id':'main','full_visible':['E','PE','CE'],
              'hint_groups':[{'text':'连接底面的中线 CE，得到 CE⊥AB。','visible':['CE']}]},
             {'step_key':'1-3','scene_id':'main','full_visible':['E','PE','CE'],
              'hint_groups':[{'text':'由 PC²=PE²+CE²，确认 PE⊥CE，再证明 PE 垂直于底面。',
                             'visible':['PE','CE'],'highlight':['PE','CE']}]},
             {'step_key':'1-4','scene_id':'main','full_visible':['E','PE','CE','base-area'],
              'hint_groups':[{'text':'底面面积为 √3，垂直高度为 √3，体积为 1。','visible':['base-area'],'highlight':['base-area','PE']}]},
         ]}
    answer=_geometry_answer(question,'立体几何',steps,'$V=1$',raw)
    return {'id':'pyramid-midpoint','label':'三棱锥 · 从中点到垂直高度','question':question,'answer_json':answer,
            'image_url':'/showcase/assets/pyramid-question.svg','image_label':'自拟题面与原始题设图',
            'source':'项目自拟教学样例；复用已校验的三棱锥构型。辅助构造与文字证明逐步对应。'}


def teaching_example(shanghai):
    return {'label':'2024 上海卷第 18 题 · 第 (1) 问','source':deepcopy(shanghai['source']),
            'prepared_example':True,'label_note':'以下对话与分支反馈为预制演示，不是真实学生记录或 AI 实时回答。',
            'question':shanghai['question'].split('\n(2)')[0],
            'steps':[
                {'title':'由图像上的点确定底数','standard_writing':r'$\log_a4=2\Rightarrow a^2=4$。结合 $a>0$，得 $a=2$。',
                 'prompt':r'图像经过 $(4,2)$，你能把它写成关于 $a$ 的等式吗？',
                 'hints':[r'点 $(4,2)$ 表示函数在 $x=4$ 时取值 $2$。',r'$\log_a4=2$ 等价于 $a^2=4$。再检查底数条件。'],
                 'wrong_answer':r'$a=\pm2$',
                 'wrong_feedback':r'指数方程有两个代数根，但对数底数要求 $a>0$ 且 $a\ne1$，只能保留 $2$。',
                 'right_answer':'$a=2$',
                 'right_feedback':'底数已确定。下一步先检查两个对数的真数是否都为正。'},
                {'title':'同时处理两个真数的定义域','standard_writing':r'$2x-2>0$ 且 $x>0$，得到 $x>1$。',
                 'prompt':'在比较真数之前，原不等式对 x 有什么限制？',
                 'hints':[r'每一个对数的真数都必须严格大于零。',r'分别写出 $2x-2>0$ 和 $x>0$，再取交集。'],
                 'wrong_answer':'只需 $x>0$。',
                 'wrong_feedback':r'还要让 $\log_2(2x-2)$ 有意义。比如 $x=\frac12$ 虽然为正，但 $2x-2<0$，原式没有定义。',
                 'right_answer':'$x>1$',
                 'right_feedback':'两个真数的正性都已检查。可以在这个范围内使用对数函数的单调性。'},
                {'title':'使用单调性，再与定义域求交集','standard_writing':r'底数 $2>1$，所以 $2x-2<x\Rightarrow x<2$。与 $x>1$ 求交集，解集为 $(1,2)$。',
                 'prompt':'底数为 2 时，不等号是否改变方向？最终还需合并哪一个条件？',
                 'hints':[r'底数大于 $1$ 时，对数函数递增，比较真数时不等号保持方向。',r'$x<2$ 还必须与上一步得到的 $x>1$ 取交集。'],
                 'wrong_answer':r'解集为 $(-\infty,2)$。',
                 'wrong_feedback':r'$x<2$ 是单调性给出的必要条件。它包含对数没有定义的值，因此必须与 $x>1$ 求交集。',
                 'right_answer':'$(1,2)$',
                 'right_feedback':'完成了“定域 → 判断单调性 → 比较真数 → 求交集”。下面换一个自拟题面，检查这条方法是否还能使用。'},
            ],
            'variant':{'prepared_example':True,'source':'项目自拟变式，不新增套路目录中的关系',
                       'question':r'【自拟变式】求不等式 $\log_2(3x-3)<\log_2(x+1)$ 的解集。',
                       'method':'沿用同一解题过程：定域 → 判断单调性 → 比较真数 → 求交集。',
                       'solution':r'真数条件给出 $3x-3>0$ 且 $x+1>0$，即 $x>1$。底数 $2>1$，所以 $3x-3<x+1$，即 $x<2$。取交集，解集为 $(1,2)$。',
                       'answer':'$(1,2)$'}}


def pool_examples(shanghai, ellipse, pyramid, catalog):
    names={r['id']:r['name'] for r in catalog['routines']}
    rows=[]
    entries=[
        ('pool-shanghai-log','对数不等式 · 公开预制题',shanghai['question'].split('\n(2)')[0],
         shanghai['answer_json']['chunk_results'][0]['final_answer'],
         r'$a=2$；$2x-2>0$ 且 $x>0$ 得 $x>1$；递增性给出 $x<2$，取交集为 $(1,2)$。',
         'EXP-006',['EXP-008'],'题设出现同底对数不等式；解析先限定真数，再使用底数大于 1 的递增性。',
         [r'$2x-2>0$ 且 $x>0$',r'$2x-2<x$',r'取交集得 $1<x<2$'],
         {'title':shanghai['source']['paper'],'url':shanghai['source']['url'],
          'publication_label':'公开高考题；解析与匹配由人工预制，仅用于展示'},None),
        ('pool-ellipse-focus','椭圆焦半径 · 自拟选择题',ellipse['question'],ellipse['answer_json']['final_answer'],
         r'设两条焦半径为 $u,v$。$u+v=2\sqrt5$，$u^2+v^2=16$，故 $uv=2$。',
         'GEO-017',['GEO-009'],'焦点三角形由题设的垂直条件形成直角；椭圆定义与勾股关系联立求乘积。',
         [r'$|PF_1|+|PF_2|=2\sqrt5$',r'$PF_1\perp PF_2$',r'$|F_1F_2|=4$'],
         {'title':'项目自拟数学演示题页 · 第 1 题','url':'/showcase/assets/ellipse-page.svg',
          'publication_label':'自拟演示材料；不是高考原件或真实审核记录'},'ellipse'),
        ('pool-pyramid-midpoint','三棱锥体积 · 自拟选择题',pyramid['question'],pyramid['answer_json']['final_answer'],
         r'取 $AB$ 中点 $E$，有 $PE=CE=\sqrt3$。由 $PC^2=PE^2+CE^2$ 得 $PE\perp CE$，进而 $PE\perp$ 平面 $ABC$。$V=\frac13\cdot\sqrt3\cdot\sqrt3=1$。',
         'SOLID-004',['SOLID-006'],'用等腰三角形中线建立两条垂线，再用勾股逆定理确认垂直关系。',
         [r'取 $AB$ 中点 $E$',r'$PA=PB=2$',r'$PC^2=PE^2+CE^2$'],
         {'title':'项目自拟数学演示题页 · 第 2 题','url':'/showcase/assets/pyramid-page.svg',
          'publication_label':'自拟演示材料；不是高考原件或真实审核记录'},'pyramid'),
    ]
    for identifier,label,question,answer,solution,primary,auxiliary,reason,evidence,source,image in entries:
        row={'id':identifier,'label':label,'question':question,'answer':answer,'solution':solution,
             'source':source,'routine_id':primary,'category':next(r['category'] for r in catalog['routines'] if r['id']==primary),
             'match':{'status':'人工编排的预制匹配样例','primary':f'{primary} · {names[primary]}','primary_id':primary,
                      'auxiliary':[f'{rid} · {names[rid]}' for rid in auxiliary],'auxiliary_ids':auxiliary,
                      'reason':reason,'evidence':'；'.join(evidence),'evidence_fragments':evidence},'review_status':'预制审核样例',
             'review_note':'本页操作只在浏览器演示状态中生效，不是原题池中的人工审核结果。'}
        if image:
            row.update(image_url=f'/showcase/assets/{image}-question.svg',image_label='自拟题面的原始题设图',
                       original_page_url=f'/showcase/assets/{image}-page.svg',original_page_label='查看自制完整题页（非原卷扫描件）',
                       options=['$1$','$2$','$4$','$2\\sqrt5$'] if image=='ellipse' else ['$\\frac13$','$1$','$\\sqrt3$','$3$'],
                       correct_option='B')
        rows.append(row)
    return rows


def library_examples(examples, pool, cube):
    rows=[{'id':e['id'],'label':e['label'],'question':e['question'],'source':deepcopy(e['source']),
           'answer':e['answer_json']['final_answer'],'category':e['answer_json']['category']['level1'],
           'prepared_example':True,'difficulty_label':'预制难度标注'} for e in examples]
    rows.extend({'id':p['id'],'label':p['label'],'question':p['question'],'source':deepcopy(p['source']),
                 'answer':p['answer'],'category':p['category'],'prepared_example':True,
                 'difficulty_label':'自拟教学样例','image_url':p.get('image_url')} for p in pool[1:])
    rows.append({'id':cube['id'],'label':cube['label'],'question':cube['question'],
                 'source':{'title':'项目自拟几何观察样例','publication_label':'自拟构造观察题，不是高考原题'},
                 'answer':cube['answer_json']['final_answer'],'category':'立体几何',
                 'prepared_example':True,'difficulty_label':'自拟构造观察样例'})
    return {'title':'成为数学高手 · 项目演示练习卷','items':rows,
            'question_ids':[e['id'] for e in rows],
            'student_pdf':'/showcase/assets/student-paper.pdf','teacher_pdf':'/showcase/assets/teacher-paper.pdf',
            'note':'固定样例题库；选择与组卷在浏览器中完成。下载文件为预制展示试卷。',
            'paper':{'title':'成为数学高手 · 项目演示练习卷','source_label':'项目自拟题与公开预制题；非正式测评',
                     'student_pdf':'/showcase/assets/student-paper.pdf','teacher_pdf':'/showcase/assets/teacher-paper.pdf'},
            'calendar':[
                {'date':'2026-10-14','title':'看见错误发生的位置','method':'回看两个真数条件','view':'diagnosis','note':'预制复习安排，不是真实学习记录。'},
                {'date':'2026-10-16','title':'无提示重做关键步骤','method':'对数不等式：定域与单调性','view':'teaching','note':'预制复习安排；反馈不会提交到个人题库。'},
                {'date':'2026-10-21','title':'用变式检查方法迁移','method':'改变真数表达式，仍然先定域再比较','view':'teaching','note':'自拟变式采用同一解题过程，不新增目录关系。'},
            ]}


def progress_snapshot():
    # Already verified local snapshot; the generator intentionally performs no
    # filesystem lookup of the owner's database or runtime review records.
    return {'as_of':'2026-10-13','scope':'本机快照','pool_items':23255,'sources':61,'occurrences':23536,
            'catalog':288,'categories':12,'classified':23138,'errors':117,'primary_matches':17005,
            'covered_routines':278,'human_confirmed':0,'server_import_confirmed':False,
            'labels':{'pool_items':'已整理的去重原题','sources':'本机来源目录','occurrences':'原题出处记录',
                      'primary_matches':'已有主套路自动建议','covered_routines':'建议覆盖的参考套路',
                      'human_confirmed':'该批次人工确认数'},
            'note':'自动匹配建议仍待人工审核；这些数字来自本机已有快照，不代表服务器已导入或真实教学效果。',
            'updates':[
                {'status':'已实现','title':'原题证据与出处回看','description':'支持原图、选项、原卷页和来源回看；跨电脑题图路径已修复。','scene':'pool'},
                {'status':'已实现','title':'套路匹配与人工复查','description':'原文证据、主／辅助套路建议、全目录复查和审核队列已建立。','scene':'pool'},
                {'status':'已实现','title':'几何步骤联动','description':'二维／三维画板可逐步显示辅助构造；参数动画与文字步骤对应。','scene':'geometry'},
                {'status':'已实现','title':'图谱布局与审核跳转','description':'既有套路图谱支持节点整理、布局保存与对应审核题目跳转。','scene':'graph'},
                {'status':'已修复','title':'侧栏与工作区稳定性','description':'侧栏栏目、布局保存和备份回滚流程已补充检查。','scene':'project'},
            ]}


def asset_sources():
    """Vector originals for our self-authored question sheets, no external URLs."""
    style='''<style>text{font-family:Arial,"PingFang SC","Microsoft YaHei",sans-serif;fill:#253448} .question{font-size:18px} .label{font-family:Georgia,serif;font-size:19px;font-style:italic} .small{font-size:13px;fill:#69778a} .edge{fill:none;stroke:#54728b;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}</style>'''
    bodies={
        'ellipse':'''<rect width="600" height="360" rx="16" fill="#fff"/>
<text x="28" y="32" class="small">项目自拟教学样例 · 原始题设图</text>
<text x="28" y="64" class="question">椭圆 C：x²/5 + y² = 1，焦点为 F₁、F₂。</text>
<text x="28" y="93" class="question">P 在椭圆上，PF₁ ⊥ PF₂。求 |PF₁| · |PF₂|。</text>
<ellipse cx="300" cy="214" rx="178.885438" ry="80" fill="#f1f5f9" stroke="#54728b" stroke-width="2.2"/>
<path d="M100 214H505" stroke="#c2cfda" stroke-width="1.4"/>
<circle cx="140" cy="214" r="4" fill="#446681"/><circle cx="460" cy="214" r="4" fill="#446681"/>
<circle cx="454.919334" cy="174" r="4.5" fill="#bd874f"/>
<text x="144" y="239" class="label">F₁</text><text x="443" y="239" class="label">F₂</text>
<text x="455" y="157" class="label">P</text>
<text x="28" y="331" class="small">题设图不含解题辅助线；画板将按推理步骤逐条显示。</text>''',
        'pyramid':'''<rect width="600" height="360" rx="16" fill="#fff"/>
<text x="28" y="32" class="small">项目自拟教学样例 · 原始题设图</text>
<text x="28" y="64" class="question">三棱锥 P-ABC 的底面是边长为 2 的等边三角形。</text>
<text x="28" y="93" class="question">PA = PB = 2，PC = √6。求三棱锥的体积。</text>
<path d="M185 287L390 287L302 214Z" fill="#edf2f7"/>
<path class="edge" d="M286 133L185 287L390 287Z M286 133L302 214L390 287"/>
<path class="edge" d="M185 287L302 214" stroke-dasharray="5 6"/>
<text x="275" y="124" class="label">P</text><text x="165" y="306" class="label">A</text>
<text x="398" y="306" class="label">B</text><text x="307" y="207" class="label">C</text>
<text x="217" y="202" class="question">2</text><text x="355" y="202" class="question">2</text>
<text x="266" y="190" class="question">√6</text><text x="281" y="311" class="question">2</text>
<text x="28" y="340" class="small">题设图不含中点及辅助线；三维画板支持旋转回看。</text>''',
    }
    result={}
    for name,body in bodies.items():
        result[f'{name}-question.svg']=f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 360" role="img" aria-label="项目自拟{'椭圆' if name=='ellipse' else '三棱锥'}题面与题设图">{style}{body}</svg>\n'''
        option_text='A．1　　　　　B．2　　　　　C．4　　　　　D．2√5' if name=='ellipse' else 'A．1/3　　　　B．1　　　　　C．√3　　　　D．3'
        number=1 if name=='ellipse' else 2
        result[f'{name}-page.svg']=f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 960" role="img" aria-label="自制完整演示题页，非高考原卷扫描件">{style}
<rect width="720" height="960" fill="#f1f3f6"/><rect x="24" y="24" width="672" height="912" rx="12" fill="#fff"/>
<text x="60" y="76" font-size="25" font-weight="700">成为数学高手 · 项目演示题页</text>
<text x="60" y="108" class="small">自制公开演示材料 / 非高考原卷扫描件 / 不含学生记录</text>
<path d="M60 130H660" stroke="#d5dce5"/><text x="60" y="163" font-size="18">第 {number} 题 · 选择题</text>
<g transform="translate(60 180)">{body}</g>
<text x="88" y="590" class="question">{option_text}</text>
<text x="60" y="641" class="small">推理与作答区（演示材料，不用于正式评分）</text>
<path d="M60 678H660 M60 734H660 M60 790H660 M60 846H660" stroke="#e0e5eb"/>
<text x="60" y="899" class="small">题面、原始题设图及选择项均为项目自拟；解析与方法匹配另行展示。</text>
</svg>\n'''
    return result


def build():
    catalog = json.loads((ROOT/'backend/routine_catalog.json').read_text())
    known = {r['id'] for r in catalog['routines']}
    if any(other not in known for r in catalog['routines'] for other in r['confusable_ids']):
        raise ValueError('套路目录引用不完整')
    shanghai = get_preset('shanghai-2024-q18')
    examples=[get_preset(p['id']) for p in public_presets()]
    geometries=[section_example(),ellipse_example(),pyramid_example()]
    pool=pool_examples(shanghai,geometries[1],geometries[2],catalog)
    return {'schema_version':2,'prepared_examples':True,
        'examples':examples,
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
        'geometry':deepcopy(geometries[0]),'geometry_examples':geometries,'teaching':teaching_example(shanghai),
        'pool_examples':pool,'library':library_examples(examples,pool,geometries[0]),'progress':progress_snapshot(),'catalog':catalog}


if __name__ == '__main__':
    destination = ROOT/'frontend/showcase/data.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    result = build()
    destination.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
    asset_root=destination.parent/'assets'
    asset_root.mkdir(exist_ok=True)
    for name,source in asset_sources().items():
        (asset_root/name).write_text(source)
    print(f"展示样例已生成：{len(result['examples'])} 道预制题，{len(result['catalog']['routines'])} 个参考套路；未读取私人数据库。")
