"""Static, fully readable teaching vision; no teaching APIs are called."""
from __future__ import annotations

import html


GROUP_COUNTS = {'students': 21, 'teachers': 17, 'schools': 17, 'society': 8}
FEATURE_TARGETS = {'#terms', '#single', '#time', '#library', '#exam', '#longterm',
                   '#teacher', '#school', '#agent', '#evolution', '#highlights'}
FEATURE_STATES = {'已有基础', '设计方案', '研究方向'}


def esc(value):
    return html.escape(str(value), quote=True)


def validate_vision(content):
    groups = content.get('groups', [])
    if [row.get('id') for row in groups] != list(GROUP_COUNTS):
        raise ValueError('Vision must retain its four ordered perspectives')
    if content.get('status') != '长期愿景':
        raise ValueError('Vision must be identified as a long-term vision')
    for group in groups:
        if len(group.get('rows', [])) != GROUP_COUNTS[group['id']]:
            raise ValueError('Incomplete vision comparisons: ' + group['id'])
        if len({row['aspect'] for row in group['rows']}) != len(group['rows']):
            raise ValueError('Duplicate vision comparison: ' + group['id'])
        for row in group['rows']:
            if not all(row.get(key) for key in ('aspect', 'before', 'after', 'features')):
                raise ValueError('Vision comparison must contain all four columns')
            for feature in row['features']:
                if feature.get('target') not in FEATURE_TARGETS:
                    raise ValueError('Unknown vision feature target: ' + str(feature))
                if feature.get('status') not in FEATURE_STATES:
                    raise ValueError('Vision feature requires an implementation status')


def feature_link(feature):
    state = feature['status']
    return ('<li><a href="' + esc(feature['target']) + '">' + esc(feature['label'])
            + '</a><span class="vision-feature-state" data-feature-state="' + state + '">'
            + state + '</span></li>')


def comparison_chain(group):
    out = ['<div class="vision-chain" aria-label="' + esc(group['title']) + '的教学变化链">']
    more_id = 'vision-more-' + group['id']
    remaining = len(group['rows']) - 2
    for index, row in enumerate(group['rows']):
        if index == 2:
            # All text is readable without JavaScript. The client initializes disclosure
            # before the main reader restores its saved scroll position.
            out.append('<button class="vision-disclosure" type="button" hidden data-vision-toggle="'
                       + group['id'] + '" data-remaining="' + str(remaining) + '" aria-expanded="true" aria-controls="'
                       + more_id + '" aria-label="收起' + esc(group['title']) + '的其余 ' + str(remaining)
                       + ' 项"><span>收起其余 ' + str(remaining) + ' 项</span>'
                       '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg></button>'
                       '<div class="vision-more" id="' + more_id + '" data-vision-more="' + group['id'] + '">')
        key = 'vision-change-' + group['id'] + '-' + str(index + 1)
        # Weight identifies the change; the complete source sentence is preserved.
        lead, stop, rest = row['after'].partition('。')
        after = '<strong>' + esc(lead + stop) + '</strong>' + esc(rest)
        out.append('<article class="vision-change" id="' + key + '" aria-labelledby="' + key + '-title">'
                   '<header class="vision-change-heading"><span class="vision-chain-dot" aria-hidden="true"></span>'
                   '<h3 id="' + key + '-title">' + esc(row['aspect']) + '</h3></header>'
                   '<div class="vision-change-flow"><div class="vision-change-before">'
                   '<span class="vision-stage-label">原来的困难</span><p>' + esc(row['before']) + '</p></div>'
                   '<div class="vision-change-connector" aria-hidden="true"><svg viewBox="0 0 56 56">'
                   '<path class="vision-arrow-wide" d="M4 12H20Q28 12 28 20V36Q28 44 36 44H51m-6-6 6 6-6 6"/>'
                   '<path class="vision-arrow-narrow" d="M12 3V44m-6-6 6 6 6-6"/></svg></div>'
                   '<div class="vision-change-result"><span class="vision-stage-label">教学怎样改变</span>'
                   '<p>' + after + '</p><div class="vision-features"><span>接续功能</span><ul>'
                   + ''.join(feature_link(feature) for feature in row['features']) + '</ul></div></div></div></article>')
    out.append('</div></div>')
    return ''.join(out)


def cost_estimate(content):
    price = content['cost_estimate']
    total = (price['input_tokens'] * price['input_per_million']
             + price['output_tokens'] * price['output_per_million']) / 1_000_000
    monthly = total * price['daily_interactions'] * price['days']
    return ('<aside class="vision-cost" aria-labelledby="vision-cost-title">'
            '<div><span class="vision-small-label">把可负担性落到预算上</span>'
            '<h3 id="vision-cost-title">一次学习帮助，模型调用需要多少钱？</h3>'
            '<p>以 GLM-5.3-Flash 为例，按未命中缓存的价格试算：</p>'
            '<dl class="vision-price-rates"><div><dt>输入 / 百万 Token</dt><dd>¥'
            + str(price['input_per_million']) + '</dd></div><div><dt>输出 / 百万 Token</dt><dd>¥'
            + str(price['output_per_million']) + '</dd></div></dl></div>'
            '<div class="vision-cost-result"><p>' + format(price['input_tokens'], ',') + ' 输入 + '
            + format(price['output_tokens'], ',') + ' 输出 Token / 次</p><strong>¥'
            + format(total, '.4f') + '<small> / 次</small></strong><p>每天 '
            + str(price['daily_interactions']) + ' 次，连续 ' + str(price['days'])
            + ' 天：<b>约 ¥' + format(monthly, '.2f') + ' / 人</b></p>'
            '<p class="vision-cost-scope">这是示例用量的模型 API 费用。完整服务预算还需计入设备、服务器、内容审核与实际调用量。</p>'
            '<a href="' + esc(price['source']) + '" target="_blank" rel="noopener noreferrer">智谱官方价格</a>'
            '<span class="vision-price-date">核对于 ' + esc(price['checked_at']) + '</span></div></aside>')


def policy_connections(content):
    out = ['<section class="vision-policy" aria-labelledby="vision-policy-title">'
           '<header><span class="vision-small-label">公共教育目标</span>'
           '<h3 id="vision-policy-title">政策方向与对应机制</h3></header><div class="vision-policy-grid">']
    for row in content['policies']:
        out.append('<article><h4>' + esc(row['title']) + '</h4><p>' + esc(row['mechanism'])
                   + '</p><p class="vision-policy-scope">' + esc(row['scope']) + '</p><a href="'
                   + esc(row['url']) + '" target="_blank" rel="noopener noreferrer">' + esc(row['document']) + '</a>')
        if row.get('mirror'):
            out.append('<a class="vision-policy-mirror" href="' + esc(row['mirror'])
                       + '" target="_blank" rel="noopener noreferrer">政府网站转载</a>')
        out.append('</article>')
    return ''.join(out) + '</div></section>'


def vision_section(content):
    validate_vision(content)
    groups = content['groups']
    skip = '<a class="vision-skip" data-vision-skip href="#highlights">跳过愿景，查看项目亮点 <span aria-hidden="true">↗</span></a>'
    out = ['<section class="topic-section vision-topic" id="vision" data-chapter="vision" aria-labelledby="heading-vision">',
           '<header class="topic-heading vision-heading"><div class="vision-heading-top">'
           '<span class="vision-status">长期愿景</span>' + skip + '</div>'
           '<h1 id="heading-vision" tabindex="-1"><span class="vision-chapter-name">教学愿景</span>'
           + esc(content['headline']) + '</h1><p class="vision-lead">' + esc(content['subtitle'])
           + '</p><p class="vision-outlook">以下对照描述系统融入日常教学后希望带来的变化。各项支撑功能的现状见对应章节。</p></header>',
           '<figure class="vision-map" aria-labelledby="vision-map-title">'
           '<figcaption id="vision-map-title">我们希望教学发生什么变化</figcaption>'
           '<div class="vision-map-root"><span>共同的学习目标</span><strong>适合每个人的支持</strong></div>'
           '<div class="vision-map-branches">']
    for group in groups:
        out.append('<a class="vision-map-branch" href="#vision-' + group['id'] + '"><strong>'
                   + esc(group['title']) + '</strong><span>' + esc(group['tagline']) + '</span></a>')
    out.extend(['</div><p class="vision-map-connection">学生作答 → 教师调整 → 学校教研 → 更普遍的学习支持<br>'
                '<span>新的讲解、资源和安排，再回到学生的下一次学习。</span></p></figure>',
                '<p class="vision-status-key"><span>功能进度</span><b>已有基础</b>已有代码或演示；<b>设计方案</b>待接入教学流程；<b>研究方向</b>待方法与效果验证。</p>',
                '<nav class="vision-outline" aria-label="愿景章内导航"><div class="vision-outline-links">'])
    for group in groups:
        out.append('<a href="#vision-' + group['id'] + '" data-vision-nav="' + group['id'] + '">'
                   + esc(group['title']) + '</a>')
    out.extend(['</div>' + skip + '</nav><div class="vision-comparisons">'])
    connections = {
        'students': ('学生的困难，成为教师下一次教学的依据。', '个人作答与复测汇成班级问题分布，教师据此决定个别辅导、小组讲解或全班重讲。'),
        'teachers': ('教学调整的结果，成为学校教研的材料。', '将采用了什么教学行动、学生随后有何变化放在一起，学校才能找到值得推广的做法和需要补充的资源。'),
        'schools': ('校内支持越及时，家庭越少需要额外补救。', '学校提供持续诊断、针对性讲解和后续复查，让更多必要的学习帮助发生在日常教育中。'),
    }
    for group in groups:
        out.append('<section class="vision-group" id="vision-' + group['id'] + '" data-vision-group="'
                   + group['id'] + '" aria-labelledby="vision-title-' + group['id'] + '">'
                   '<header class="vision-group-heading"><span>' + esc(group['tagline']) + '</span><h2 id="vision-title-'
                   + group['id'] + '" tabindex="-1">' + esc(group['title']) + '</h2><p>'
                   + esc(group['summary']) + '</p></header>' + comparison_chain(group) + '</section>')
        if group['id'] in connections:
            title, text = connections[group['id']]
            out.append('<aside class="vision-connection"><span aria-hidden="true">↓</span><div><strong>'
                       + esc(title) + '</strong><p>' + esc(text) + '</p></div></aside>')
    out.append('</div>' + cost_estimate(content) + policy_connections(content))
    out.append('<div class="vision-conclusion"><p>我们希望看到的成效，是学生能独立解决新问题、隔一段时间仍然会用，教师的调整有后续结果，家庭少一些无效投入。</p></div>')
    out.append('<div class="chapter-bridge"><div class="bridge-flow"><div class="bridge-output"><span>希望改变的教学日常</span>'
               '<strong>学生学习、教师教学、学校教研与社会支持</strong></div><div class="bridge-track" aria-hidden="true">'
               '<svg viewBox="0 0 180 32"><path d="M5 16H173m-7-6 7 6-7 6"/></svg><i class="bridge-packet"></i></div>'
               '<div class="bridge-input"><span>接下来说明</span><strong>系统怎样实现这些变化</strong></div></div>'
               '<a class="chapter-transition" href="#highlights" data-vision-skip>这些变化如何实现？从项目亮点开始'
               '<span>方法、时间、能力图谱与教学协同</span><svg viewBox="0 0 24 24" aria-hidden="true">'
               '<path d="M4 12h15m-6-6 6 6-6 6"/></svg></a></div></section>')
    return ''.join(out)
