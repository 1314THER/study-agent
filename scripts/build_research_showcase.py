"""Build the readable research walkthrough from reviewed chapter content.

No model calls or private database access. The source map is checked before a
chapter is published so edits to its Markdown cannot silently go unnoticed.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path

if __package__:
    from .showcase_vision import validate_vision, vision_section
    from .showcase_highlight_visuals import (system_visual, method_visual, time_visual,
                                            ability_visual, data_visual, participation_visual, evolution_visual)
else:
    from showcase_vision import validate_vision, vision_section
    from showcase_highlight_visuals import (system_visual, method_visual, time_visual,
                                          ability_visual, data_visual, participation_visual, evolution_visual)

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'frontend/showcase'
CHAPTER_IDS = ['overview', 'concepts', 'dataset', 'single', 'diagnosis', 'library', 'routines',
               'exam', 'career', 'agent', 'teacher', 'school', 'modes', 'mcp', 'evolution']
TOPICS = [
    {'id': 'vision', 'title': '教学愿景', 'sources': [],
     'thesis': '让每个学生，都能获得适合自己的学习支持。',
     'bridge': ('学生、教师、学校与社会的教学变化', '系统怎样实现这些变化')},
    {'id': 'highlights', 'title': '亮点', 'sources': ['overview', 'dataset'],
     'thesis': '让 AI 参与学习全过程，推动每一次教学。',
     'bridge': ('方法、时间、能力图谱与持续改进', '课时、知识点、步骤与套路怎样连接教学')},
    {'id': 'terms', 'title': '系统底层名词的定义与作用', 'sources': ['concepts'],
     'thesis': '课时组织教学，知识点衡量理解，步骤描述操作，套路组织方法。',
     'bridge': ('统一的教学对象与前置关系', '同一道题的结构化解题与分步反馈')},
    {'id': 'single', 'title': '单题能力', 'sources': ['single'],
     'thesis': 'AI 解题建立参考，批改定位表现，教学提供支持，出题形成下一次练习。',
     'bridge': ('参考解法、步骤判断与教学记录', '静态答案遗漏的作答先后与修改过程')},
    {'id': 'time', 'title': '时间维度', 'sources': ['diagnosis'],
     'thesis': '把笔迹事件放回步骤顺序，先看见疑点，再安排能区分原因的验证。',
     'bridge': ('带时间顺序的步骤证据', '可查找、可复练、可复测的题目记录')},
    {'id': 'library', 'title': '题库与错题', 'sources': ['library', 'routines'],
     'thesis': '从错误步骤找到相似任务，再把套路练习转成独立迁移与延迟复查。',
     'bridge': ('围绕缺口组织的题单与迁移表现', '把单题和训练放进整卷目标中检验')},
    {'id': 'exam', 'title': '考试与复盘', 'sources': ['exam'],
     'thesis': '分开评价试卷是否适合目标，以及学生怎样完成这份试卷。',
     'bridge': ('本次试卷、作答与时间证据', '这些变化在长期学习中是否持续')},
    {'id': 'longterm', 'title': '长期陪伴', 'sources': ['career'],
     'thesis': '汇总连续作业和阶段考试，随新作答更新知识理解与套路运用记录。',
     'bridge': ('带来源、帮助条件与复测结果的个人记录', '谁来查询证据并把它变成教学行动')},
    {'id': 'teacher', 'title': '教师工作流', 'sources': ['teacher'],
     'thesis': '从备课到阶段调整，根据个别困难安排课堂讲解、作业和新题复测。',
     'bridge': ('教师行动与后续学习变化', '学校怎样提供可比评估与体系支持')},
    {'id': 'school', 'title': '学校与教学采用方式', 'sources': ['school', 'modes'],
     'thesis': '学校可以维护教学体系，也可以从一个环节开始接入并逐步扩展。',
     'bridge': ('明确接入范围与版本边界的教育能力', '不同 Agent 入口怎样安全调用共同业务')},
    {'id': 'agent', 'title': 'MCP与Agent能力', 'sources': ['agent', 'mcp'],
     'thesis': '学生、教师与学校从不同入口提出任务，底层教育业务与记录保持一致。',
     'bridge': ('可复用的业务任务与结果', '反馈如何经过核验成为下一版本')},
    {'id': 'evolution', 'title': '自进化', 'sources': ['evolution'],
     'thesis': '收集反馈与新题，核验内容和规则的修改，再用后续学习表现检验更新。',
     'bridge': ('经过复核、评测和小范围试用的系统更新', '用后续独立作答检查更新效果')},
]
TOPIC_IDS = [row['id'] for row in TOPICS]
PERSPECTIVES = [('teaching', '教学应用'), ('technical', '技术实现')]
UNIT_LABELS = {
    'overview': '一个错误答案，后续支持常常断开',
    'concepts': '四个对象，构成共同教学语言',
    'dataset': '题目怎样找到知识与方法坐标',
    'single': '同一份步骤结构，连接四项单题能力',
    'diagnosis': '静态结果看不到的作答过程',
    'library': '从错因标定到独立复测',
    'routines': '从套路顺序到知识准备的双路训练',
    'exam': '评价试卷质量，也分析学生作答',
    'career': '把不同来源的学习证据汇入长期记录',
    'teacher': '从个别错误走到班级教学行动',
    'school': '学校评价与底层体系维护',
    'modes': '完整采用与传统教学增强',
    'agent': '不同角色的教学协同任务',
    'mcp': 'MCP接口适配，迎接AI Agent时代',
    'evolution': '反馈、新题与教学规则怎样形成更新',
}
# Narrative units read better as one column; management units keep their key
# technical points in view but fold the long-form details away.
SINGLE_LANE = {'concepts', 'career', 'exam', 'diagnosis'}
FOLDED_LANE = {'teacher', 'school', 'modes'}
MERGED_UNITS = SINGLE_LANE | FOLDED_LANE
RELATIONSHIPS = {    'concepts': ('同一道题中的教学对象', '稳定标识与前置关系', '统一定义与解法映射', '知识、步骤与套路判断'),
    'single': ('题目与学生作答', '三阶段解析与步骤对齐', '步骤判断与训练目标', '讲解与针对性练习'),
    'diagnosis': ('笔迹、停顿与返回修改', '时间对齐与步骤依赖', '首错、传播与待核实疑点', '追问、补测与自我复盘'),
    'library': ('错误步骤与复练目标', '题目索引与训练状态', '匹配题目与复查任务', '补一步、练套路、再复测'),
    'routines': ('方法选择与练习表现', '六步状态机与双路推荐', '适用条件与下一步任务', '独立迁移与延迟复查'),
    'exam': ('试卷模板与学生作答记录', '逐题解析核验、整卷检查与作答事件整理', '试卷目标符合度与失分步骤', '调整试卷、核实原因并安排补测'),
    'career': ('作业、考试与帮助条件', '事件账本与正反证据', '可以修订的长期判断', '按当前困难安排学习'),
    'teacher': ('学生困难与课堂目标', '班级聚合与干预跟踪', '分组建议与后续表现', '作业、讲评与教学调整'),
    'school': ('教学规则与校本要求', '依赖分析与版本管理', '影响范围与可比口径', '教研支持与校本定制'),
    'modes': ('实际接入的教学环节', '可用证据与能力矩阵', '可支持的功能与判断', '逐步采用与局部增强'),
    'agent': ('学生、教师与学校请求', '身份、记忆与工具编排', '可追溯的任务与结果', '解释、执行与持续跟进'),
    'mcp': ('不同宿主中的教学任务', '共用契约与业务任务编号', '统一结果与恢复状态', '换入口后接着完成'),
    'evolution': ('教师反馈、联网新题与教材变化', '来源核验、更新草稿与独立测试', '待审核的新题、内容或规则修改', '审核发布后跟踪学习效果'),
}
KEY_PHRASES = {
    'overview': ['共同的教学表示', '定位错误步骤', '独立新题复测'],
    'concepts': ['教学顺序', '知识点支撑解题步骤', '多解路径不绑定唯一参考解'],
    'single': ['结构化参考', '三阶段链路', '学生作答', '针对性'],
    'diagnosis': ['观察事实', '传播结果', '假设和未知', '时间同步', '步骤及其依赖关系'],
    'library': ['每次作答', '已核实错因', '独立复测'],
    'routines': ['方法识别', '双路', '独立迁移', '知识准备'],
    'exam': ['教学目标', '逐题解析核验', '学生作答', '无法归属的时间'],
    'career': ['知识理解与套路表现', '帮助条件', '相反证据', '两条路线'],
    'teacher': ['教学行动', '复测结果', '个性化作业'],
    'school': ['多来源依据', '版本化变更', '依赖影响分析'],
    'modes': ['完整系统模式', '传统教学增强模式', '接入的环节'],
    'agent': ['已认证', '检查真实返回', '后续安排'],
    'mcp': ['MCP 工具', '任务编号', '同一份教育业务与学习档案'],
    'evolution': ['联网发现', '更新草稿', '独立测试', '知识库', '规则'],
}
# Only explicit limitations are cautions; a study's neutral task scope stays neutral.
RESEARCH_GAPS = [
    '模型常选中接近却不完全相同的标准', '第三项没有得到同样改善',
    '18 个受测模型的 F1 均低于 0.5，模糊证据下更差', '补写未出现的推理、把不足的证据当成明确依据',
    '自由书写中的前后依赖，仍需另行识别', '要判断对应哪个数学步骤、学生为何停顿，仍需结合题目和作答核查',
    '概念是否理解、推荐是否改善学习，还需另外检验', '学生学习效果仍需另做实验',
    '情境题的通过率仍低于标准题，迭代后可解性也并非在所有设置下最好',
    '较难据此判断学生状态并选择合适的教学行动', '固定分解也可能增加负担，限制其他解题路径',
    '具体权重和量规需要在本地教学条件下重新校准',
    'GPT Base 组平均考试分较对照低约 17%（相对变化）', '不支持 MCP prompt templates',
    '教育应用需要另行定义学习目标、评分标准和验证方法',
    '仍需学生独立完成新题的实验来评价学习收益', '教学经验的效用判断需结合真实学习结果',
    '学生能否迁移方法、间隔后能否保持，需要另做独立作答实验',
    '反馈能否改变后续学习行为还需真实课堂检验',
]

TECHNICAL_ROUTES = {
    'overview': ('把课时、知识点、步骤、套路与题目组织成可引用的教学对象；单题输出进入训练、复测和班级行动。', '对同一案例检查对象引用、步骤证据和后续任务是否连续，缺少数据时保留未知。'),
    'concepts': ('采用稳定标识区分教学对象、前置关系、可复用步骤与题目中的实例步骤；多解路径不绑定唯一参考解。', '变更关系或拆分概念后检查引用、历史版本和题目映射；分别报告覆盖缺失与尚未标注。'),
    'dataset': ('整理题目来源与出处，抽取候选知识、步骤、套路映射，再进入置信度筛选和人工核验。当前规模快照与规划测算分开保存。', '核对样本去重、来源可追溯、候选与确认状态、映射版本和汇总口径；不把规划数量当作已完成标注。'),
    'single': ('当前三阶段链路由公开大模型 API、任务提示词和 JSON 结构保护组成：Solver 先解题，Verifier 校验并组织分步，Formatter 整理约定结构和实例难度。批改、教学、出题继续复用现有模型提示词与后端检查。', '保存每阶段输入输出与模型配置；检查 JSON 解析、参考解正确性、步骤完整性、学生多解法和生成题可解性。当前不是专门微调模型。'),
    'diagnosis': ('采集数字笔笔画的坐标、时间、起落笔和修改事件；进行时间同步、事件分段，再与题目步骤及其依赖关系对齐。规则与模型输出区分观察事实、传播结果、假设和未知。', '验证时钟漂移、断点补传、笔迹对齐和首错传播；用同信息基线比较诊断位置及追问价值。停顿本身不作心理或知识结论。'),
    'library': ('分离题目、参考解、每次作答和训练任务；按题目、步骤、知识点、套路与已核实错因建立检索索引。六步循环保存阶段，套路表现与知识准备采用两路候选推荐。', '检查相似题是否满足方法边界、同一次错误是否被重复计数、提示后与独立完成是否分开、复查任务是否重复。'),
    'routines': ('用状态机记录方法识别、学习、仿练、无提示重做、变式迁移和延迟复查；以套路前置顺序生成默认路径，再用知识准备证据调整任务。', '对比套路顺序、知识 readiness 与双路推荐；用隐藏方法标签的新题和延迟复测测独立迁移，不以流程通过率替代掌握结论。'),
    'exam': ('模板规定知识范围、题型、分值、总时长和难度。先确定教学目标、安排卷面结构，再选题或出题，逐题解析核验后检查整卷覆盖与难度。学生作答另外整理首次作答、回看修改和无法归属的时间，结合失分步骤、历史表现、学生说明及后续补测核实原因。', '分别核对试卷是否符合模板，以及学生失分原因是否有作答依据；检查覆盖、题目可解性、难度分布与评分点。用时只依据真实采集的事件，首笔至末笔不等于全部思考时间；两道全国卷只作内容示例，不补造学生用时。'),
    'career': ('保存不可覆盖的作答事件及来源、帮助条件、题目版本、步骤表现和复测关系；分别维护知识理解与套路表现，并允许相反证据触发修订。', '用无提示新题及间隔后的任务检验判断；分别记录漏交、未考查、看过答案和原题重做。'),
    'teacher': ('基于授权班级范围聚合步骤表现，记录统计分母、识别覆盖、教师复核和教学行动；任务按学生或小组分配，复测结果回连到行动。', '核对提交与识别情况，以及题目难度和帮助条件；记录建议采用情况、教师用时和后续新题表现，由教师决定教学安排。'),
    'school': ('以组织、班级和校本体系配置隔离权限；课时、知识点、步骤或套路调整进入版本化变更，先做依赖影响分析，再审核发布并保留历史报告口径。', '对旧记录执行明确映射或补充诊断；分别评价完整采用和局部接入能支持的结论与数据条件。'),
    'modes': ('按接入方式列明数据与功能：作业和试卷提供题目与作答，照片、PDF、文本和数字笔迹提供不同形式的记录；缺少原始时间线时，用时标为缺失。', '建立数据与功能对应表，再通过试点比较学习结果、接入成本、教师用时，以及新增记录是否改善判断。'),
    'agent': ('将自然语言任务编排到已认证的学生、教师或学校业务；查询档案、调用工具、检查真实返回并保存任务状态。内置助教负责领域解释，外部宿主负责通用会话。', '分别检查各角色的访问权限、任务中断后的恢复和结果来源；记忆注明来源与时间，未核实推测单列。'),
    'mcp': ('将课程、题库、批改、练习、学情和报告封装成带参数、身份范围、结果结构与错误语义的 MCP 工具。官方 DSH 和 WorkBuddy 是适配方向，需针对各宿主单独验收。', '检查访问权限是否限定在任务所需范围、重复请求是否只执行一次、任务能否超时恢复，以及结果是否过滤敏感字段；所有调用继续由后端核对业务权限。'),
    'evolution': ('已有采集链路可从指定公开题源联网发现、下载、识别和切题，保存来源并接收到素材池。核验题干与解析、去重并对应知识与方法目录后，形成待审核的新题；教师反馈和教材变化另整理为内容或规则修改草稿。知识库、提示词、规则与模型按各自路线独立测试、审核和版本发布，采集新题不等于自动训练模型。', '依次检查收集反馈与新题、核对与去重、整理更新草稿、独立测试、审核发布和跟踪学习效果。按题目族和学生划分训练与测试数据，核对原有任务、新任务和旧版回退；跨学科复用任务、档案与工具，另建知识结构和评价标准。'),
}
STATUS = {'implemented': '已有实现', 'prototype': '设计方案', 'research': '研究方向', 'mixed': '已有基础'}
NAV_LABELS = {row['id']: row['title'] for row in TOPICS}
CHAPTER_TO_TOPIC = {chapter_id: topic['id'] for topic in TOPICS for chapter_id in topic['sources']}


def esc(value):
    return html.escape(str(value), quote=True)


def validate_source_map(content, mapping):
    """Fail closed if any chapter no longer matches its fully read sources."""
    rows = mapping.get('chapters', [])
    if [row.get('id') for row in rows] != CHAPTER_IDS:
        raise ValueError('Source map must cover all fifteen chapters in order')
    vision = json.loads((PUBLIC / 'vision-content.json').read_text())
    validate_vision(vision)
    vision_map = mapping.get('vision', {})
    if vision_map.get('title') != vision['title'] or vision_map.get('status') != vision['status']:
        raise ValueError('Vision source map title/status differs')
    if [row['file'] for row in vision_map.get('sources', [])] != vision.get('source_docs'):
        raise ValueError('Vision source map files differ')
    if len({source['file'] for row in rows + [vision_map] for source in row.get('sources', [])}) != mapping.get('source_count'):
        raise ValueError('Source map source_count does not match unique source files')
    docs_root = (ROOT / 'docs').resolve()
    for chapter, mapped in zip(content['chapters'], rows):
        if chapter.get('title') != mapped.get('title'):
            raise ValueError(f"Source map title differs for {chapter['id']}")
        expected_files = ['docs/' + name for name in chapter.get('source_docs', [])]
        sources = mapped.get('sources', [])
        if [source.get('file') for source in sources] != expected_files:
            raise ValueError(f"Source map files differ for {chapter['id']}")
        expected_urls = [row.get('url') for row in chapter.get('research', [])]
        if mapped.get('research_urls', []) != expected_urls:
            raise ValueError(f"Research source map differs for {chapter['id']}")
        resources = [{'title': row['title'], 'website': row.get('website_url', row['url']),
                      'paper_or_document': row.get('paper_url', row.get('source_url', row['url']))}
                     for row in chapter.get('research', [])]
        if mapped.get('research_resources') != resources:
            raise ValueError(f"Research website/document mapping differs for {chapter['id']}")
        if chapter['id'] == 'dataset':
            snapshot = mapped.get('aggregate_snapshot', {})
            raw = (PUBLIC / 'dataset-data.json').read_bytes()
            if snapshot.get('file') != 'frontend/showcase/dataset-data.json' or hashlib.sha256(raw).hexdigest() != snapshot.get('sha256'):
                raise ValueError('Dataset aggregate snapshot changed; re-audit before rebuilding')
        for source in sources:
            if source.get('read_completeness') != 'full':
                raise ValueError(f"Source was not marked as fully read: {source.get('file')}")
            path = (ROOT / source['file']).resolve()
            if not path.is_relative_to(docs_root) or not path.is_file():
                raise ValueError(f"Source path is missing or outside docs/: {source.get('file')}")
            raw = path.read_bytes()
            text = raw.decode('utf-8')
            if hashlib.sha256(raw).hexdigest() != source.get('sha256'):
                raise ValueError(f"Source hash changed; reread and remap chapter: {source['file']}")
            if len(text.splitlines()) != source.get('line_count'):
                raise ValueError(f"Source line count changed; reread and remap chapter: {source['file']}")
    for source in vision_map.get('sources', []):
        path = (ROOT / source['file']).resolve()
        if not path.is_relative_to(docs_root) or not path.is_file() or source.get('read_completeness') != 'full':
            raise ValueError('Vision source was not fully read: ' + source['file'])
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source.get('sha256') or len(raw.decode().splitlines()) != source.get('line_count'):
            raise ValueError('Vision source hash changed; reread and remap: ' + source['file'])
    if vision_map.get('content_sha256') != hashlib.sha256((PUBLIC / 'vision-content.json').read_bytes()).hexdigest():
        raise ValueError('Vision content changed; review its source mapping')


def marked_text(value, phrases=(), cls='key-phrase'):
    phrases = sorted({phrase for phrase in phrases if phrase in value}, key=len, reverse=True)
    if not phrases:
        return esc(value)
    pattern = re.compile('|'.join(re.escape(phrase) for phrase in phrases))
    out, end = [], 0
    for match in pattern.finditer(value):
        out.extend([esc(value[end:match.start()]), '<strong class="' + cls + '">' + esc(match.group()) + '</strong>'])
        end = match.end()
    return ''.join(out) + esc(value[end:])


def paragraphs(value, phrases=(), cls='key-phrase'):
    return ''.join('<p>' + marked_text(row, phrases, cls) + '</p>' for row in (value if isinstance(value, list) else [value]) if row)


def research_logic(row):
    logic = row.get('logic')
    if not logic:
        return ''
    stages = logic.get('stages', [])
    parallel = logic.get('layout') == 'parallel'
    arrow = '<span class="logic-arrow" aria-hidden="true">→</span>'
    node = lambda text, kind, i: '<div class="logic-node logic-' + kind + '" style="--stage:' + str(i) + '"><span>' + {'input': '输入', 'method': '方法', 'output': '产出'}[kind] + '</span><strong>' + esc(text) + '</strong></div>'
    out = ['<figure class="research-logic"><figcaption>研究逻辑</figcaption><div class="logic-flow' + (' logic-parallel' if parallel else '') + '">', node(logic['input'], 'input', 0), arrow]
    if parallel:
        out.append('<div class="logic-task-group">' + ''.join(node(text, 'method', i + 1) for i, text in enumerate(stages)) + '</div>')
    else:
        out.append(arrow.join(node(text, 'method', i + 1) for i, text in enumerate(stages)))
    out.extend([arrow, node(logic['output'], 'output', len(stages) + 1), '</div>'])
    if logic.get('feedback'):
        out.append('<p class="logic-feedback">↶ ' + esc(logic['feedback']) + '</p>')
    out.append('</figure>')
    return ''.join(out)


def bank_markup():
    return '''<div class="native-workbench" id="bank-workbench">
<div class="workbench-bar"><strong>全国卷公开案例题库</strong><span id="bank-total"></span>
<div class="segmented-control" role="tablist" aria-label="题库工作区">
<button type="button" data-library-tab="library" role="tab" aria-selected="true">题库</button>
<button type="button" data-library-tab="exam" role="tab" aria-selected="false">组卷</button>
<button type="button" data-library-tab="calendar" role="tab" aria-selected="false">复查</button></div></div>
<div id="bank-toolbar" class="bank-toolbar">
<label>查找题目<input id="bank-search" name="question-search" type="search" autocomplete="off" placeholder="例如：数列、2025 全国卷…"></label>
<label>板块<select id="bank-category"><option value="">全部板块</option></select></label>
<label>题型<select id="bank-type"><option value="">全部题型</option></select></label>
<label>年份<select id="bank-year"><option value="">全部年份</option></select></label>
<label>来源<select id="bank-source"><option value="">全部来源</option></select></label></div>
<div id="bank-actions" class="bank-actions"><span id="bank-result-count" role="status"></span>
<span id="bank-selection" role="status">选择题目后可组卷</span>
<button id="bank-clear-routine" type="button" hidden>清除套路筛选</button>
<button id="bank-clear-selection" type="button" disabled>清空选题</button>
<button id="bank-build-exam" type="button" disabled>组卷预览</button></div>
<div id="library-layout" class="library-layout is-library">
<section class="library-items" data-library-panel="library" aria-label="全国卷题目列表">
<div id="library-list"><p>正在读取全国卷案例…</p></div><div class="bank-pagination">
<button id="bank-prev" type="button">上一页</button><span id="bank-page-label"></span><button id="bank-next" type="button">下一页</button></div></section>
<section id="bank-detail" data-library-panel="library" aria-label="题目详情" aria-live="polite"></section>
<section class="exam-card" data-library-panel="exam" hidden><div class="workbench-bar"><strong>当前选题</strong>
<div><button id="exam-student" type="button" aria-pressed="true">学生版</button><button id="exam-teacher" type="button" aria-pressed="false">教师版</button></div></div>
<div id="exam-preview"></div><div class="exam-bottom"><button id="exam-print" type="button">打印当前选题</button></div></section>
<section class="calendar-card" data-library-panel="calendar" hidden><p>复查时间与任务为流程示意，不是学生的真实学习记录。</p><div id="calendar-content"></div></section>
</div></div>'''


def references(chapter):
    rows = chapter.get('research', [])
    if not rows:
        return ''
    out = ['<section class="research-notes" aria-label="现有研究与本项目的关系"><h3>现有研究</h3>']
    for row in rows:
        url = str(row.get('source_url') or row.get('url', ''))
        if not url.startswith('https://'):
            raise ValueError('Research links must be HTTPS: ' + url)
        resource_type = row.get('resource_type', 'paper')
        site_label, paper_label = {'paper': ('研究页面', '论文原文'), 'software': ('项目网站', '方法文档'), 'protocol': ('官方网站', '协议文档'), 'report': ('项目网页', '研究报告')}[resource_type]
        out.append('<article class="research-study"><header><h4>' + esc(row['title']) + '</h4></header><div class="research-source-links">')
        for label, target in [(site_label, row.get('website_url', row['url'])), (paper_label, row.get('paper_url', url))]:
            if not str(target).startswith('https://'):
                raise ValueError('Research resources must use HTTPS')
            out.append('<a href="' + esc(target) + '" target="_blank" rel="noopener noreferrer"><strong>' + label + ' ↗</strong><span>' + esc(target) + '</span></a>')
        out.append('</div>' + research_logic(row) + '<div class="research-grid"><div class="research-prior"><span class="research-side-label">已有研究</span>')
        fields = [('task', '研究任务'), ('method', '具体方法'), ('findings', '研究结果')]
        if not any(row.get(key) for key, _ in fields):
            fields = [('contribution', '已有研究做了什么')]
        for key, title in fields + [('scope', '任务范围')]:
            if row.get(key):
                scope_class = ' class="research-scope"' if key == 'scope' else ''
                title = '研究范围' if key == 'scope' else title
                out.append('<div' + scope_class + '><h5>' + title + '</h5>' + paragraphs(row[key], RESEARCH_GAPS, 'research-gap') + '</div>')
        if row.get('source_location'):
            out.append('<p class="research-location">' + esc(row['source_location']) + '</p>')
        out.append('</div><div class="research-project"><span class="research-side-label">StudyAgent</span>')
        for key, title in [('response', '对应的系统机制'), ('validation', '对照验证')]:
            if row.get(key):
                out.append('<div class="research-' + key + '"><h5>' + title + '</h5>' + paragraphs(row[key]) + '</div>')
        out.append('</div></div>')
        if row.get('version') or row.get('source_refs'):
            out.append('<p class="research-citations">' + esc(row.get('version', '')))
            for ref in row.get('source_refs', []):
                if not str(ref.get('url', '')).startswith('https://'):
                    raise ValueError('Additional research links must use HTTPS')
                out.append(' · <a href="' + esc(ref['url']) + '" target="_blank" rel="noopener noreferrer">' + esc(ref['title']) + ' ↗</a>')
            out.append('</p>')
        out.append('</article>')
    out.append('</section>')
    return ''.join(out)


def scene_markup(chapter):
    key = chapter['id']
    content = bank_markup() if key == 'library' else '<p class="scene-loading">正在准备交互图解…</p>'
    return '<div id="scene-' + key + '" class="chapter-scene" aria-label="' + esc(chapter['title']) + '图解与演示">' + content + '</div>'


def perspective_cell(perspective, body, source_id, heading):
    label = dict(PERSPECTIVES)[perspective]
    return ('<article class="perspective-cell" data-perspective-cell="' + perspective + '" data-perspective-label="' +
            esc(label) + '" data-source-unit="' + source_id + '"><h3 class="cell-kicker">' +
            esc(heading) + '</h3>' + body + '</article>')


def legacy_anchors(source_id):
    # Old chapter URLs now land on the corresponding unit inside its new topic.
    aliases = {
        'single': ['solution', 'grading', 'teaching', 'generation', 'geometry'],
        'routines': ['graph'], 'library': ['pool'],
        'evolution': ['progress', 'research'],
    }
    anchors = []
    if source_id not in TOPIC_IDS:
        anchors.append(source_id)
    anchors.extend(aliases.get(source_id, []))
    return ''.join('<span id="' + esc(anchor) + '" class="anchor-alias" aria-hidden="true"></span>' for anchor in anchors)


def sentence_bullets(text):
    parts = [part.strip() for part in re.split(r'[；。]', text) if part.strip()]
    return ''.join('<li>' + esc(part) + '</li>' for part in parts)


def tech_points(chapter):
    """Every key technical item stays visible; only the long-form detail folds."""
    source_id = chapter['id']
    summary, _ = TECHNICAL_ROUTES[source_id]
    groups = [('技术路径', sentence_bullets(summary))]
    if chapter.get('mechanism'):
        groups.append(('处理机制', ''.join('<li>' + esc(item) + '</li>' for item in chapter['mechanism'])))
    if chapter.get('details'):
        groups.append(('重点细节', ''.join('<li>' + esc(detail['title']) + '</li>' for detail in chapter['details'])))
    if chapter.get('research'):
        groups.append(('现有研究', ''.join('<li>' + esc(row['title']) + '</li>' for row in chapter['research'])))
    out = ['<section class="unit-tech-points" aria-label="技术要点">']
    for label, items in groups:
        out.append('<h4>' + label + '</h4><ul>' + items + '</ul>')
    out.append('</section>')
    return ''.join(out)


def unit_markup(chapter, index):
    source_id = chapter['id']
    key = 'unit-' + source_id
    label = UNIT_LABELS[source_id]
    status = chapter['status']
    teaching = []
    if chapter.get('pain'):
        pain = chapter['pain']
        teaching.append('<div class="pain-point"><span>现实痛点</span><h4>' + esc(pain['title']) + '</h4>' + paragraphs(pain['text']) + '</div>')
    teaching.append(scene_markup(chapter))
    teaching.append('<div class="chapter-prose">' + paragraphs(chapter.get('body', []), KEY_PHRASES.get(source_id, ())) + '</div>')

    notes = []
    if chapter.get('details'):
        notes.append('<div class="mechanism-notes">')
        for number, detail in enumerate(chapter['details'], 1):
            notes.append('<aside class="margin-note"><h4>' + esc(detail['title']) + '</h4>' + paragraphs(detail['body']) + '</aside>')
        notes.append('</div>')
    notes.append(references(chapter))

    summary, acceptance = TECHNICAL_ROUTES[source_id]
    technical = []
    technical.append('<div class="technical-status"><span class="status status-' + status + '">' + STATUS[status] + '</span><span>' + esc(chapter.get('kicker', '')) + '</span></div>')
    technical.append('<h4 id="route-' + source_id + '">技术路径</h4><p class="technical-summary" data-relation-anchor="' + source_id + '">' + marked_text(summary, KEY_PHRASES.get(source_id, ())) + '</p>')
    if chapter.get('mechanism'):
        technical.append('<ol class="mechanism-list">' + ''.join('<li>' + esc(item) + '</li>' for item in chapter['mechanism']) + '</ol>')
    technical.append('<div class="acceptance-note"><strong>验证重点</strong><p>' + esc(acceptance) + '</p></div>')

    linked = source_id in {'overview', 'concepts', 'single', 'diagnosis', 'library', 'routines', 'exam', 'career', 'teacher', 'school', 'agent', 'mcp', 'evolution'}
    merged_class = ' is-merged' if source_id in MERGED_UNITS else ''
    out = ['<section class="topic-unit' + merged_class + '" data-link-unit="' + key + '" data-source-id="' + source_id + '" data-related-processing="' + esc(RELATIONSHIPS.get(source_id, ('', '', '', ''))[1]) + '" id="unit-anchor-' + source_id + '">']
    out.append(legacy_anchors(source_id))
    if linked:
        out.append('<button class="topic-unit-key" type="button" data-link-focus="' + key + '" aria-pressed="false"><strong>' + esc(label) + '</strong><span class="unit-key-action">对应技术</span></button>')
    else:
        out.append('<div class="topic-unit-key"><strong>' + esc(label) + '</strong></div>')
    merged = source_id in MERGED_UNITS
    if merged:
        # One reading column: teaching first, then the technical lane below it.
        out.append('<div class="topic-unit-grid is-single">')
        out.append(perspective_cell('teaching', '<div class="cell-content">' + ''.join(teaching) + '</div>', source_id, '课堂与学生作答'))
        inner = []
        if source_id in FOLDED_LANE:
            inner.append(tech_points(chapter))
        inner.append(''.join(technical + notes))
        lane = ['<div class="unit-lane unit-tech" data-source-unit="' + source_id + '"><div class="cell-content">'
                + ''.join(inner) + '</div></div>']
        out.append(''.join(lane))
        out.append('</div>')
    else:
        out.append('<div class="topic-unit-grid">')
        out.append(perspective_cell('teaching', '<div class="cell-content">' + ''.join(teaching) + '</div>', source_id, '课堂与学生作答'))
        out.append('<div class="lane-divider" data-lane-divider><div class="lane-divider-control" data-split-control role="separator" tabindex="0" aria-label="调整教学应用与技术实现的宽度" aria-orientation="vertical" aria-valuemin="35" aria-valuemax="75" aria-valuenow="60" aria-valuetext="教学应用 60%，技术实现 40%"></div></div>')
        out.append(perspective_cell('technical', '<div class="cell-content">' + ''.join(technical + notes) + '</div>', source_id, '机制、研究与技术实现'))
        out.append('</div>')
    out.append('</section>')
    return ''.join(out)


def topic_section(topic, topic_index, chapters):
    key = topic['id']
    first_heading = 'h1' if topic_index == 1 else 'h2'
    out = ['<section class="topic-section" id="' + key + '" data-chapter="' + key + '" aria-labelledby="heading-' + key + '">']
    out.append('<header class="topic-heading">')
    out.append('<' + first_heading + ' id="heading-' + key + '">' + esc(topic['title']) + '</' + first_heading + '><p class="chapter-thesis">' + esc(topic['thesis']) + '</p></header>')
    if not all(source_id in MERGED_UNITS for source_id in topic['sources']):
        out.append('<div class="perspective-headings" aria-hidden="true">' + ''.join('<h3>' + esc(label) + '</h3>' for _, label in PERSPECTIVES) + '</div>')
    for unit_index, source_id in enumerate(topic['sources'], 1):
        out.append(unit_markup(chapters[source_id], unit_index))
    output, next_question = topic['bridge']
    next_id = TOPIC_IDS[topic_index] if topic_index < len(TOPIC_IDS) else ''
    if next_id:
        next_title = NAV_LABELS[next_id]
        out.append('<div class="chapter-bridge"><div class="bridge-flow"><div class="bridge-output"><span>本主题形成共同产物</span><strong>' + esc(output) + '</strong></div><div class="bridge-track" aria-hidden="true"><svg viewBox="0 0 180 32"><path d="M5 16H173m-7-6 7 6-7 6"/></svg><i class="bridge-packet"></i></div><div class="bridge-input"><span>下一个主题要回答</span><strong>' + esc(next_question) + '</strong></div></div>')
        out.append('<a class="chapter-transition" href="#' + next_id + '">继续：' + esc(next_title) + ' <span>' + esc(next_question) + '</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h15m-6-6 6 6-6 6"/></svg></a></div>')
    else:
        # The last topic closes with one prominent invitation back to the vision.
        out.append('<div class="chapter-bridge chapter-bridge-closing"><a class="chapter-transition chapter-transition-closing" href="#vision">'
                   '<strong>读完了方案和技术路线，再回去看看愿景。</strong>'
                   '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h15m-6-6 6 6-6 6"/></svg></a></div>')
    out.append('</section>')
    return ''.join(out)


def launch_screen(copy):
    """A separate first-visit screen; the full story stays in the document."""
    lettering = (PUBLIC / 'launch-lettering.svg').read_text()
    lettering = lettering.replace('<svg ', '<svg class="hero-love" aria-hidden="true" ', 1)
    return ''.join(['<dialog class="launch-screen" id="launch-screen" aria-labelledby="launch-title">' + (PUBLIC / 'launch-geometry.svg').read_text() + '<div class="launch-layout">',
           '<header class="launch-brand"><img src="/showcase/assets/fudan-emblem-white.png" width="40" height="40" alt="复旦大学校徽"><span><strong>步骤级诊断与方法迁移训练系统</strong><small>StudyAgent 科研项目</small></span></header>',
           '<div class="highlights-hero launch-hero"><div class="hero-copy"><h2 id="launch-title" tabindex="-1">' + ''.join('<span>' + esc(part + ('，' if i == 0 else '')) + '</span>' for i, part in enumerate(copy['title'].split('，', 1))) + '</h2><p class="hero-subtitle">' + esc(copy['subtitle']) + '</p></div>',
           '<div class="hero-art" id="hero-art" data-phase="waiting" aria-label="数学 love 书写与探索入口">' + lettering,
           '<svg class="hero-ink-link" aria-hidden="true"><path id="hero-ink-path" pathLength="1"/></svg>',
           '<a id="explore-start" class="explore-start" href="#vision"><span class="explore-glass" aria-hidden="true"></span><strong>开始探索</strong><span class="explore-icon" aria-hidden="true">↗</span></a></div>',
           '<div class="hero-manifesto"><p>' + esc(copy['manifesto']) + '</p><p lang="en">' + esc(copy['manifesto_en']) + '</p></div></div>',
           '<footer class="launch-footer"><div class="launch-contact"><span>项目负责人：施棋智</span><a href="mailto:qzshi25@m.fudan.edu.cn">email：qzshi25@m.fudan.edu.cn</a></div><nav aria-label="正式站与备案"><a href="https://150.chat/" target="_blank" rel="noopener noreferrer">正式站（正在开发中）</a><a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">渝ICP备2026024246号-1</a></nav></footer></div></dialog>'])


def highlights_section(copy):
    """A visual story for each argument, with one compact map of all ten modules."""
    visuals = {'system': system_visual, 'methods': method_visual, 'time': time_visual,
               'ability': ability_visual, 'data': data_visual, 'participation': participation_visual,
               'evolution': evolution_visual}
    out = ['<section class="topic-section highlights-topic" id="highlights" data-chapter="highlights" aria-labelledby="heading-highlights">',
           '<span id="overview" class="anchor-alias" aria-hidden="true"></span>',
           '<header class="topic-heading"><h2 id="heading-highlights" tabindex="-1">' + esc(copy['label']) + '</h2></header>',
           '<div class="highlights-body">']
    metrics = json.loads((PUBLIC / 'dataset-data.json').read_text())['headline_metrics']
    for point in copy['points']:
        key = point['id']
        out.append('<article class="highlight-point highlight-feature highlight-' + key + '" id="highlight-' + key + '" aria-labelledby="highlight-title-' + key + '"><div class="highlight-narrative"><header><span class="highlight-index">' + esc(point['label']) + '</span><h2 id="highlight-title-' + key + '">' + esc(point['title']) + '</h2></header>')
        if point.get('pain'):
            out.append('<p class="highlight-pain"><span>现实痛点</span>' + esc(point['pain']) + '</p>')
        if point.get('score'):
            out.append('<div class="full-score"><strong>2<span>×</span>150</strong><span>' + esc(point['score_caption']) + '</span></div>')
        if point.get('intro'):
            out.append('<p>' + esc(point['intro']) + '</p>')
        out.append('<p class="highlight-body">' + esc(point['body']) + '</p>')
        out.append('<p class="highlight-key"><strong>' + esc(point['key']) + '</strong></p>')
        if point.get('bridge'):
            out.append('<p class="highlight-connection">' + esc(point['bridge']) + '</p>')
        out.append('</div><div class="highlight-visual-slot">' + visuals[key]() + '</div>')
        if key == 'data':
            out.append('<div id="scene-dataset" class="highlight-data-foot"><span id="dataset" class="anchor-alias" aria-hidden="true"></span><dl class="highlight-metrics">' + ''.join('<div class="dataset-metric"><dt>' + esc(row['unit']) + '</dt><dd>' + format(row['value'], ',') + '</dd></div>' for row in metrics if row['key'] in {'knowledge', 'steps', 'routines', 'pool'}) + '</dl><a class="highlight-dataset-link" href="/showcase/dataset.html">查看数据集规模 ↗</a></div>')
        if point.get('comparison'):
            out.append('<div class="openness-comparison"><table><thead><tr><th scope="col">封闭题库的常见形态</th><th scope="col">StudyAgent 的设计方向</th></tr></thead><tbody>' + ''.join('<tr><td>' + esc(a) + '</td><td>' + esc(b) + '</td></tr>' for a, b in point['comparison']) + '</tbody></table></div>')
        out.append('</article>')
    out.append('</div><div class="highlight-closing"><p>' + esc(copy['closing']) + '</p></div><div class="chapter-bridge"><div class="bridge-flow"><div class="bridge-output"><span>这套系统连接起</span><strong>方法 · 时间 · 能力 · 教学行动</strong></div><div class="bridge-track" aria-hidden="true"><svg viewBox="0 0 180 32"><path d="M5 16H173m-7-6 7 6-7 6"/></svg><i class="bridge-packet"></i></div><div class="bridge-input"><span>先认识共同使用的</span><strong>课时 · 知识点 · 步骤 · 套路</strong></div></div><a class="chapter-transition" href="#terms">继续：四个名词介绍 <span>' + esc(copy['next']) + '</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h15m-6-6 6 6-6 6"/></svg></a></div></section>')
    return ''.join(out)


def build(content):
    source_chapters = content['chapters']
    if [c['id'] for c in source_chapters] != CHAPTER_IDS:
        raise ValueError('The fifteen reviewed source units must retain their order')
    chapter_map = {chapter['id']: chapter for chapter in source_chapters}
    if set(CHAPTER_TO_TOPIC) != set(CHAPTER_IDS):
        raise ValueError('Each reviewed source unit must map to exactly one topic')
    primary_nav = ''.join('<a href="#' + topic['id'] + '" title="' + esc(topic['thesis']) + '">' + esc(topic['title']) + '</a>' for i, topic in enumerate(TOPICS))
    mobile_options = ''.join('<option value="' + topic['id'] + '">' + esc(topic['title']) + '</option>' for i, topic in enumerate(TOPICS))
    vision = json.loads((PUBLIC / 'vision-content.json').read_text())
    sections = ''.join(vision_section(vision) if topic['id'] == 'vision' else highlights_section(content['highlights']) if topic['id'] == 'highlights' else topic_section(topic, index + 1, chapter_map) for index, topic in enumerate(TOPICS))
    perspective_controls = ''.join('<button type="button" role="tab" aria-selected="' + ('true' if key == 'teaching' else 'false') + '" data-perspective="' + key + '">' + esc(label) + '</button>' for key, label in PERSPECTIVES)
    return '''<!doctype html>
<html lang="zh-CN"><head><style>html{background:#000}</style><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="StudyAgent：从学生、教师、学校到社会，探索针对性教学与普惠学习支持。通过全国卷案例了解步骤诊断、方法训练与长期陪伴。">
<meta name="theme-color" content="#080808"><meta name="color-scheme" content="dark"><title>步骤级诊断与方法迁移训练系统 · StudyAgent</title>
<link rel="icon" type="image/svg+xml" href="/showcase/assets/fudan-emblem-mono.svg">
<link rel="icon" type="image/png" sizes="64x64" href="/showcase/assets/fudan-favicon.png">
<link rel="shortcut icon" type="image/x-icon" href="/favicon.ico">
<link rel="apple-touch-icon" sizes="180x180" href="/showcase/assets/fudan-favicon-180.png">
<link rel="stylesheet" href="/style.css"><link rel="stylesheet" href="/vendor/katex/katex.min.css"><link rel="stylesheet" href="/showcase/style.css"><link rel="stylesheet" href="/showcase/handwriting.css"><link rel="stylesheet" href="/showcase/transitions.css"><link rel="stylesheet" href="/showcase/hero.css"><link rel="stylesheet" href="/showcase/surfaces.css"><link rel="stylesheet" href="/showcase/launch-geometry.css"><link rel="stylesheet" href="/showcase/highlights.css"><link rel="stylesheet" href="/showcase/highlights-layout.css"><link rel="stylesheet" href="/showcase/vision.css">
<script defer src="/vendor/katex/katex.min.js"></script><script defer src="/dimchart.js"></script><script defer src="/radar.js"></script><script defer src="/showcase/handwriting.js"></script><script defer src="/showcase/bank.js"></script><script defer src="/showcase/liquid-glass.js"></script><script defer src="/showcase/hero.js"></script><script defer src="/showcase/vision.js"></script><script defer src="/showcase/app.js"></script><script defer src="/showcase/splitter.js"></script><script defer src="/showcase/transitions.js"></script><script defer src="/showcase/highlights.js"></script>
</head><body class="research-showcase">''' + launch_screen(content['highlights']) + '''<script>try{var _d=document.getElementById('launch-screen');if(_d&&!location.hash&&!sessionStorage.getItem('studyagent.showcase.reading.v1')){_d.showModal();document.body.classList.add('is-launch-open');}}catch(_e){}</script><a class="skip-link" href="#main-content">跳到项目内容</a>
<header class="site-header"><a class="research-brand" href="#vision"><img class="brand-emblem" src="/showcase/assets/fudan-emblem-white.png" width="44" height="44" alt="复旦大学校徽"><span>步骤级诊断与方法迁移训练系统<small>StudyAgent 科研项目</small></span></a>
<nav class="primary-nav" aria-label="章节导航">''' + primary_nav + '''</nav>
<label class="topic-quick-jump"><span class="sr-only">跳转到主题</span><select id="topic-quick-jump" aria-label="跳转到主题">''' + mobile_options + '''</select></label></header>
<main id="main-content"><div class="page-intro"><span>高中数学 / 过程诊断 / 方法迁移</span><span>全国卷案例 · 从作答到教学</span></div>
<nav class="perspective-switch" aria-label="选择阅读视角"><div class="perspective-switch-label"><strong>阅读视角</strong><span class="swipe-hint">左右滑动切换</span></div><div class="perspective-tabs" role="tablist" aria-label="教学应用与技术实现">''' + perspective_controls + '''</div></nav>
<p id="demo-status" class="page-status" role="alert" hidden></p>''' + sections + '''</main>
<footer class="site-footer"><div><strong>StudyAgent</strong><p>让每次作答，成为下一步学习的依据。</p></div><div><a href="https://150.chat/" target="_blank" rel="noopener noreferrer">正式站（正在开发中）</a><a href="https://github.com/1314THER/study-agent" target="_blank" rel="noopener noreferrer">代码与研究文档</a><a href="#highlights">回到系统亮点</a></div><p class="site-registration"><a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">渝ICP备2026024246号-1</a></p><p class="site-author">项目负责人：施棋智<br>email：<a href="mailto:qzshi25@m.fudan.edu.cn">qzshi25@m.fudan.edu.cn</a></p></footer>
<aside id="annotation-panel" class="annotation-panel" aria-label="补充批注" hidden><header><h2 id="annotation-title"></h2><button id="annotation-close" type="button" aria-label="关闭批注">×</button></header><div id="annotation-body"></div></aside>
<noscript><style>.chapter-scene:not(:has(.native-workbench)):not(#scene-dataset){display:none}</style><p class="noscript-note">正文、逻辑图、数据集与现有研究可直接阅读。</p></noscript>
</body></html>'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    content = json.loads((PUBLIC / 'research-content.json').read_text())
    mapping = json.loads((ROOT / 'docs/showcase-content-map.json').read_text())
    validate_source_map(content, mapping)
    result = build(content)
    target = PUBLIC / 'index.html'
    if args.check:
        if not target.exists() or target.read_text() != result:
            raise SystemExit('Showcase HTML does not match reviewed chapter content')
    else:
        target.write_text(result)
    print('Verified twelve linked topics' if args.check else 'Built twelve linked topics')


if __name__ == '__main__':
    main()
