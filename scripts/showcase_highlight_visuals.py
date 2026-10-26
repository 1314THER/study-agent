"""Static, accessible diagrams for the showcase's first chapter.

Every function returns complete HTML. The diagrams explain their relationships
without JavaScript; highlights.js only adds local motion and optional controls.
"""
from html import escape
from textwrap import dedent


def _clean(markup):
    return dedent(markup).strip()


def _icon(name):
    paths = {
        'learn': '<path d="m4 7 8-4 8 4-8 4-8-4Zm3 3v6c3 3 7 3 10 0v-6M20 7v8"/>',
        'steps': '<path d="M8 4H5v16h14V4h-3M9 3h6v4H9zM9 12h7M9 16h5"/><path d="m7 12 .5.5L9 11"/>',
        'target': '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><path d="m12 12 8-8M16 4h4v4"/>',
        'exam': '<path d="M6 3h12v18H6zM9 8h6M9 12h6M9 16h3"/><path d="m14 16 1 1 3-3"/>',
        'archive': '<path d="M4 7h16v4H4zM6 11v9h12v-9M9 15h6M7 3h10"/>',
        'teach': '<path d="M3 4h18v12H3zM8 21l4-5 4 5M7 9h5M7 12h8M16 7l2 2-2 2"/>',
        'expert': '<path d="m4 8 4 3 4-7 4 7 4-3-2 11H6L4 8ZM8 22h8"/>',
        'ai': '<path d="M8 5h8l3 3v8l-3 3H8l-3-3V8l3-3ZM9 9h6v6H9zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
        'teacher': '<path d="M9 7h12v11H11M14 11h4M14 14h3"/><circle cx="5" cy="7" r="3"/><path d="M1 21v-8h8v8M9 14l4-3"/>',
    }
    return '<svg class="hx-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths[name] + '</svg>'


def system_visual():
    """A compact map of the ten chapters, with four main causal connections."""
    def card(key, title, body, icon):
        return ('<a class="architecture-node hx-system-node" href="#' + key + '">'
                + _icon(icon) + '<div><strong>' + title + '</strong><small>' + body + '</small></div></a>')
    representation = card('terms', '四个名词，各管一件事', '课时 · 一元一次方程（这节课教什么）<br>知识点 · 等式性质（为什么成立）<br>步骤 · 两边减 3（具体操作）<br>套路 · 一元一次方程求解方法（组合与适用条件）', 'learn')
    learning = ''.join([
        card('single', '单题能力', '解题 · 批改 · 教学 · 出题', 'steps'),
        card('time', '时间维度', '笔迹 · 单题 · 整卷 · 生涯', 'archive'),
        card('library', '题库与错题', '检索与错因 · 步骤补练<br>套路循环 · 双路推荐', 'target'),
        card('exam', '考试与复盘', '模板 · 组卷 · 评价 · 改卷<br>时间与失分分析', 'exam'),
        card('longterm', '长期陪伴', '两路建档 · 知识与套路掌握<br>能力图谱 · 独立复测 · 长期助教', 'learn'),
    ])
    teaching = ''.join([
        card('teacher', '教师工作流', '备课与演示课件 · 个性作业<br>批改讲评 · 出卷改卷 · 阶段调整 · 人工关注', 'teacher'),
        card('school', '学校与采用', '教学质量与教师评价 · 底层体系定制<br>完整采用 · 传统教学增强', 'teach'),
    ])
    openness = ''.join([
        card('agent', 'MCP 与 Agent', '角色沟通 · 记忆 · 工具调度<br>DSH · WorkBuddy', 'ai'),
        card('evolution', '自进化', '教师反馈 · 人工维护 · 新题与教材<br>知识库与模型改进 · 跨学科扩展', 'archive'),
    ])
    return _clean('''<figure class="hx-visual hx-system-visual highlight-system-map project-architecture" id="scene-overview" data-hx-motion="system">
      <figcaption><strong>十个功能，共用一套教学逻辑</strong><span>表示连接功能，学习形成证据，证据改变教学，新的反馈再回到系统。</span></figcaption>
      <div class="hx-system-graph" data-hx-graph>
        <svg class="hx-wires" data-hx-wires data-hx-marker="hx-system-arrow" data-hx-edges='[["representation","student"],["student","teaching"],["teaching","open"],["open","representation","return"]]' aria-hidden="true"><defs><marker id="hx-system-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M1 1 9 5 1 9" fill="none" stroke="currentColor" stroke-width="1.5"/></marker></defs></svg>
        <div class="hx-system-layer hx-representation-layer" data-hx-port="representation"><div class="hx-layer-label"><strong>共用表示</strong><span>每个环节说同一种语言</span></div><div class="hx-system-cards">''' + representation + '''</div></div>
        <div class="hx-layer-connection"><span aria-hidden="true">↓</span><strong>共同对象与方法结构</strong></div>
        <div class="hx-system-layer hx-student-layer" data-hx-port="student"><div class="hx-layer-label"><strong>学生学习链</strong><span>学习 → 步骤批改 → 针对训练 → 考试复盘 → 长期档案</span></div><div class="hx-system-cards">''' + learning + '''</div></div>
        <div class="hx-layer-connection"><span aria-hidden="true">↓</span><strong>学习证据推动教学调整</strong></div>
        <div class="hx-system-layer hx-teaching-layer" data-hx-port="teaching"><div class="hx-layer-label"><strong>教师与学校行动</strong><span>改变下一次出题、教学与复习</span></div><div class="hx-system-cards">''' + teaching + '''</div></div>
        <div class="hx-layer-connection"><span aria-hidden="true">↓</span><strong>能力向外连接，经验回流更新</strong></div>
        <div class="hx-system-layer hx-open-layer" data-hx-port="open"><div class="hx-layer-label"><strong>开放与演进</strong><span>Agent 调用各层能力，反馈经审核再更新</span></div><div class="hx-system-cards">''' + openness + '''</div></div>
      </div>
      <p class="hx-figure-note hx-return-note"><span aria-hidden="true">↺</span> 反馈与教学结果 → 更新共同表示和能力 → 改变下一轮学习与教学</p>
    </figure>''')


def method_visual():
    return _clean('''
        <figure class="hx-visual hx-method-visual" data-hx-motion="method" data-hx-stage="0">
          <figcaption><strong>同一道题，看清四个单位</strong><span>概念示例：解 2x + 3 = 11</span></figcaption>
          <div class="hx-method-context"><div><span>课时 · 组织教学</span><strong>一元一次方程</strong><small>这一节课学什么</small></div><div><span>知识点 · 说明依据</span><strong>等式性质</strong><small>理解两边为什么可以同做运算</small></div></div>
          <div class="hx-method-dependency"><span>这三个操作都用到等式性质</span><svg viewBox="0 0 220 24" aria-hidden="true"><path d="M2 12h212m-7-6 7 6-7 6"/></svg></div>
          <div class="hx-routine-bracket"><div class="hx-routine-heading"><span>套路 · 组合解题步骤</span><strong>一元一次方程求解方法</strong></div><ol class="hx-equation-steps" aria-label="这个套路中的三个步骤"><li data-hx-method-step="0"><span>步骤 · 两边减 3</span><strong>2x = 8</strong><small>应用等式性质，消去常数项</small></li><li data-hx-method-step="1"><span>步骤 · 两边除以 2</span><strong>x = 4</strong><small>应用等式性质，求出未知数</small></li><li data-hx-method-step="2"><span>步骤 · 代回检验</span><strong>2 × 4 + 3 = 11</strong><small>核对结果是否满足原方程</small></li></ol></div>
          <div class="hx-controls hx-method-controls" data-hx-controls hidden aria-label="查看例题的步骤"><button type="button" data-hx-method="0" aria-pressed="true">减去常数</button><button type="button" data-hx-method="1" aria-pressed="false">求出未知数</button><button type="button" data-hx-method="2" aria-pressed="false">代回检验</button></div>
          <p class="hx-figure-note">知识点说明每步为什么成立；步骤记录具体怎么做；套路组织这些步骤，并说明何时使用。</p>
        </figure>
    ''')


def time_visual():
    return _clean('''
        <figure class="hx-visual hx-time-visual" data-hx-motion="time" data-hx-stage="0">
          <figcaption><strong>答案之外，还有过程</strong><span>从单题，到整卷，再到整个学习历程</span></figcaption>
          <div class="hx-time-scale hx-time-question"><div class="hx-scale-label"><strong>一道题</strong><span>步骤怎样发生</span></div><div class="hx-time-detail"><div class="hx-writing-track"><span class="hx-time-segment hx-write">书写</span><span class="hx-time-segment hx-pause">停顿</span><span class="hx-time-segment hx-rewrite">返回修改</span><i class="hx-time-cursor" aria-hidden="true"></i></div><div class="hx-time-annotations"><span>开始推导</span><strong>停顿所在步骤</strong><span>返回修改</span></div></div></div>
          <div class="hx-time-scale"><div class="hx-scale-label"><strong>一张卷</strong><span>时间怎样分配</span></div><div class="hx-paper-time"><div><span>前段作答</span><i style="--hx-bar:54%"></i></div><div class="hx-time-overrun"><span>反复尝试</span><i style="--hx-bar:86%"></i><small>是否挤占后续作答？</small></div><div><span>后段作答</span><i style="--hx-bar:30%"></i></div></div></div>
          <div class="hx-time-scale"><div class="hx-scale-label"><strong>长期</strong><span>变化是否保持</span></div><div class="hx-history"><span><i></i>作业发现</span><b aria-hidden="true">→</b><span><i></i>订正补练</span><b aria-hidden="true">→</b><span><i></i>独立复测</span></div></div>
          <p class="hx-figure-note">将错误位置、作答顺序和历史表现相互核对，再用追问或补测核实失分原因。</p>
        </figure>
    ''')


def ability_visual():
    dimensions = [
        ('知识板块', '看知识点覆盖、同类任务的稳定表现与延迟复查。'),
        ('做题能力', '看能否独立选择方法、完成关键步骤并迁移到新题。'),
        ('计算能力', '看计算步骤的准确性、熟练度与反复出错的位置。'),
        ('逻辑推理', '看推导链条、条件使用与论证是否完整严密。'),
        ('数学素养', '看数学表达、抽象建模以及跨情境理解与迁移。'),
        ('考试技巧与心态', '查看时间分配、回访策略与复测；心态结合学生自述和教师交流了解。'),
    ]
    controls = ''.join('<button type="button" data-hx-dimension="' + str(i) + '" aria-pressed="' + ('true' if i == 0 else 'false') + '">' + escape(label) + '</button>' for i, (label, _) in enumerate(dimensions))
    evidence = ''.join('<div data-hx-evidence="' + str(i) + '"' + (' class="is-selected"' if i == 0 else '') + '><dt>' + escape(label) + '</dt><dd>' + escape(text) + '</dd></div>' for i, (label, text) in enumerate(dimensions))
    return _clean('''
        <figure class="hx-visual hx-ability-visual" data-hx-motion="ability" data-hx-profile="a" data-hx-dimension-active="0">
          <figcaption><strong>同一个分数，可以有不同的形状</strong><span>虚构示例 · 六个维度，呈现不同短板</span></figcaption>
          <div class="hx-radar-wrap"><svg class="hx-radar" viewBox="0 0 600 420" role="img" aria-labelledby="hx-radar-title hx-radar-description"><title id="hx-radar-title">刘同学与侠同学的六维能力图谱（虚构示例）</title><desc id="hx-radar-description">六个维度为知识板块、做题能力、计算能力、逻辑推理、数学素养、考试技巧与心态。刘同学知识、做题与计算接近满分，但心态、数学素养与逻辑推理薄弱；侠同学心态突出，其余维度一般。两者均为虚构示例。</desc><g class="hx-radar-grid" fill="none"><path d="M300 77 420 146 420 284 300 353 180 284 180 146Z"/><path d="M300 111.5 390 163.25 390 266.75 300 318.5 210 266.75 210 163.25Z"/><path d="M300 146 360 180.5 360 249.5 300 284 240 249.5 240 180.5Z"/><path d="M300 180.5 330 197.75 330 232.25 300 249.5 270 232.25 270 197.75Z"/></g><g class="hx-radar-axes"><path data-hx-axis="0" d="M300 215V77"/><path data-hx-axis="1" d="M300 215 420 146"/><path data-hx-axis="2" d="M300 215 420 284"/><path data-hx-axis="3" d="M300 215V353"/><path data-hx-axis="4" d="M300 215 180 284"/><path data-hx-axis="5" d="M300 215 180 146"/></g><polygon class="hx-radar-ghost" points="300,139 360,181 360,250 300,284 234,253 186,150"/><polygon class="hx-radar-shape" data-hx-radar-shape points="300,81 410,152 414,281 300,250 274,230 264,194"/><g class="hx-radar-labels" text-anchor="middle"><text x="300" y="48">知识板块</text><text x="490" y="122">做题能力</text><text x="490" y="311">计算能力</text><text x="300" y="391">逻辑推理</text><text x="110" y="311">数学素养</text><text x="110" y="112"><tspan x="110">考试技巧</tspan><tspan x="110" dy="23">与心态</tspan></text></g><g class="hx-radar-dots" data-hx-radar-dots></g></svg></div>
          <div class="hx-controls hx-profile-controls" data-hx-controls hidden aria-label="切换示例能力档案"><button type="button" data-hx-profile-button="a" aria-pressed="true">刘同学（做题家）</button><button type="button" data-hx-profile-button="b" aria-pressed="false">侠同学（心态型）</button></div>
          <div class="hx-controls hx-dimension-controls" data-hx-controls hidden aria-label="选择能力维度，查看证据来源">''' + controls + '''</div>
          <dl class="hx-evidence-list">''' + evidence + '''</dl>
          <p class="hx-figure-note">刘同学与侠同学均为虚构示例：同样的分数，能力与心态的形态可以完全不同，后续的支持安排也因此因人而异。点击轮廓上的圆点，可查看该维度的判断依据。</p>
        </figure>
    ''')


def data_visual():
    contributors = [
        ('expert', 'expert', '满分高手', '提炼方法与考场经验'),
        ('ai', 'ai', '顶级 AI', '辅助拓展、整理与校验'),
        ('teacher', 'teacher', '学校数学教师', '校准表达与评分依据'),
    ]
    sources = ''.join('<div class="hx-data-source" data-hx-port="' + key + '">' + _icon(icon) + '<strong>' + title + '</strong><span>' + body + '</span><b class="hx-static-arrow" aria-hidden="true">↓</b></div>' for key, icon, title, body in contributors)
    return _clean('''
        <figure class="hx-visual hx-data-visual" data-hx-motion="data">
          <figcaption><strong>把人的经验，编成共同的知识</strong><span>三方共编，各自提供不同的判断依据</span></figcaption>
          <div class="hx-data-graph" data-hx-graph><svg class="hx-wires" data-hx-wires data-hx-marker="hx-data-arrow" data-hx-edges='[["expert","base","merge"],["ai","base","merge"],["teacher","base","merge"]]' aria-hidden="true"><defs><marker id="hx-data-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M1 1 9 5 1 9" fill="none" stroke="currentColor" stroke-width="1.5"/></marker></defs></svg><div class="hx-data-contributors">''' + sources + '''</div><div class="hx-data-base" data-hx-port="base"><div class="hx-base-layers" aria-hidden="true"><i></i><i></i><i></i></div><strong>可解释、可训练的知识底座</strong><span>知识点 <b>·</b> 步骤 <b>·</b> 套路 <b>·</b> 适用条件</span></div></div>
          <p class="hx-figure-note">共同编订的结构，为解题、批改、教学和出题提供依据。</p>
        </figure>
    ''')


def participation_visual():
    return _clean('''
        <figure class="hx-visual hx-participation-visual" data-hx-motion="participation" data-hx-stage="0">
          <figcaption><strong>发现之后，还要追踪改变</strong><span>反馈进入教学现场，再用后续作答检验</span></figcaption>
          <div class="hx-action-headings" aria-hidden="true"><span>看见问题</span><span>采取行动</span><span>检查效果</span></div>
          <ol class="hx-action-rows"><li><div class="hx-action-problem"><span>学生</span><strong>同一步反复卡住</strong></div><b aria-hidden="true">→</b><div class="hx-action-response"><strong>针对性补练</strong><span>回到薄弱操作</span></div><b aria-hidden="true">→</b><div class="hx-action-check"><strong>独立复测</strong><span>能否独立完成</span></div></li><li><div class="hx-action-problem"><span>班级</span><strong>共同困难集中出现</strong></div><b aria-hidden="true">→</b><div class="hx-action-response"><strong>调整讲评与作业</strong><span>改变下一次教学</span></div><b aria-hidden="true">→</b><div class="hx-action-check"><strong>后续作答</strong><span>共同困难是否减少</span></div></li><li><div class="hx-action-problem"><span>教研</span><strong>阶段问题持续反复</strong></div><b aria-hidden="true">→</b><div class="hx-action-response"><strong>反馈备课与教研</strong><span>形成新的教学安排</span></div><b aria-hidden="true">→</b><div class="hx-action-check"><strong>持续追踪</strong><span>改进能否保持</span></div></li></ol>
          <div class="hx-action-return"><span aria-hidden="true">↺</span><strong>效果再次成为反馈</strong><span>提出建议只是开始，后续证据决定是否继续调整。</span></div>
        </figure>
    ''')


def evolution_visual():
    return _clean('''
        <figure class="hx-visual hx-evolution-visual" data-hx-motion="evolution" data-hx-stage="0">
          <figcaption><strong>能力向外连接，经验向内积累</strong><span>经过审核与评测的改进，才能回到教学</span></figcaption>
          <div class="hx-open-tools"><div><strong>不同助教与教师工具</strong><span>通过开放工具接口调用</span></div><span class="hx-interface-link" aria-hidden="true">⇄</span><div><strong>共同的教育能力</strong><span>解题 · 批改 · 出题 · 学情</span></div></div>
          <div class="hx-evolution-input"><span>新试题</span><span>教材变化</span><span>教师纠错</span><span>后续学习结果</span></div>
          <div class="hx-evolution-flow"><span class="hx-flow-intro">形成候选</span><span aria-hidden="true">↓</span><ol><li><span class="hx-cycle-symbol" aria-hidden="true">⤓</span><strong>AI 辅助整理校验</strong><small>核对结构与来源</small></li><li><span class="hx-cycle-symbol" aria-hidden="true">✓</span><strong>教师审核</strong><small>校准教学与评分依据</small></li><li><span class="hx-cycle-symbol" aria-hidden="true">⌁</span><strong>离线评测</strong><small>确认改进及影响范围</small></li><li><span class="hx-cycle-symbol" aria-hidden="true">↗</span><strong>发布与教学再验证</strong><small>让新经验服务更多场景</small></li></ol><div class="hx-evolution-return"><span aria-hidden="true">↺</span><strong>知识库 · 规则 · 模型</strong><span>教学产生新反馈，继续进入下一轮。</span></div></div>
        </figure>
    ''')


VISUALS = {
    'system': system_visual,
    'methods': method_visual,
    'time': time_visual,
    'ability': ability_visual,
    'data': data_visual,
    'participation': participation_visual,
    'openness': evolution_visual,
}
