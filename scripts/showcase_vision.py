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
    if content.get('status') != '教学愿景':
        raise ValueError('Vision must be identified as the teaching vision')
    for group in groups:
        if len(group.get('rows', [])) != GROUP_COUNTS[group['id']]:
            raise ValueError('Incomplete vision comparisons: ' + group['id'])
        if len({row['aspect'] for row in group['rows']}) != len(group['rows']):
            raise ValueError('Duplicate vision comparison: ' + group['id'])
        for row in group['rows']:
            if not all(row.get(key) for key in ('aspect', 'before', 'after', 'features', 'short_vision')):
                raise ValueError('Vision comparison must contain all four columns')
            if len(row['short_vision']) > 14:
                raise ValueError('Short vision exceeds fourteen characters')
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
    out = ['<div class="vision-viewport"><div class="vision-world">'
           '<svg class="vision-orbits" aria-hidden="true"></svg>']
    for index, row in enumerate(group['rows']):
        key = 'vision-change-' + group['id'] + '-' + str(index + 1)
        out.append('<article class="vision-change" id="' + key + '" data-aspect="' + esc(row['aspect']) + '">'
                   '<button class="vision-card" type="button" hidden aria-haspopup="dialog" aria-controls="vision-dialog" '
                   'aria-label="' + esc(group['title'] + '：' + row['aspect'] + '，' + row['short_vision'] + '，查看现状与愿景') + '">'
                   + esc(row['short_vision']) + '</button><details class="vision-fallback"><summary>'
                   + esc(row['aspect']) + ' · ' + esc(row['short_vision']) + '</summary>'
                   '<div class="vision-detail"><div class="vision-change-flow"><div class="vision-change-before">'
                   '<span class="vision-stage-label">现状</span><p>' + esc(row['before']) + '</p></div>'
                   '<div class="vision-change-connector" aria-hidden="true"><svg viewBox="0 0 100 40">'
                   '<defs><linearGradient id="gradient-' + key + '"><stop stop-color="#FF7B86"/>'
                   '<stop offset="1" stop-color="#8AB8FF"/></linearGradient></defs>'
                   '<path d="M4 20H92m-12-12 12 12-12 12" stroke="url(#gradient-' + key + ')"/></svg></div>'
                   '<div class="vision-change-result"><span class="vision-stage-label">愿景</span><p>'
                   + esc(row['after']) + '</p></div></div><div class="vision-features"><span>接续功能</span><ul>'
                   + ''.join(feature_link(feature) for feature in row['features']) + '</ul></div></div></details></article>')
    return ''.join(out) + '</div></div><div class="vision-camera-controls" hidden><button type="button" data-camera-step="-1" aria-label="上一项愿景">上一项</button><span class="vision-camera-count"></span><button type="button" data-camera-step="1" aria-label="下一项愿景">下一项</button><span class="sr-only" role="status"></span></div>'


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
            + ' 天（一周）：<b>约 ¥' + format(monthly, '.2f') + ' / 周 / 人</b></p>'
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
    out = ['<a class="vision-skip" data-vision-skip href="#highlights">跳过愿景，查看项目亮点 <span aria-hidden="true">↗</span></a>'
           '<section class="topic-section vision-topic" id="vision" data-chapter="vision" aria-labelledby="heading-vision">'
           '<header class="topic-heading vision-heading"><h1 id="heading-vision" tabindex="-1"><span class="vision-chapter-name">教学愿景</span>'
           + esc(content['headline']) + '</h1><p class="vision-lead">' + esc(content['subtitle'])
           + '</p><p class="vision-outlook">以下展示融入日常教学后的目标形态。点击一块愿景，查看现状、完整设想与支撑功能。</p></header>'
           '<nav class="vision-outline" aria-label="愿景章内导航"><div class="vision-outline-links">']
    for group in content['groups']:
        out.append('<a href="#vision-' + group['id'] + '" data-vision-nav="' + group['id'] + '">' + esc(group['title']) + '</a>')
    out.append('</div></nav><p class="vision-status-key">功能进度：已有基础 · 设计方案 · 研究方向；各项现状见详情。</p><div class="vision-comparisons">')
    for group in content['groups']:
        out.append('<section class="vision-group" id="vision-' + group['id'] + '" data-vision-group="' + group['id']
                   + '" aria-labelledby="vision-title-' + group['id'] + '"><header class="vision-group-heading"><h2 id="vision-title-'
                   + group['id'] + '" tabindex="-1">' + esc(group['title']) + '</h2><p>' + esc(group['tagline']) + '</p></header>'
                   + comparison_chain(group) + '</section>')
    out.append('</div><dialog id="vision-dialog" class="vision-dialog" aria-labelledby="vision-dialog-title"><header class="vision-dialog-head">'
               '<h2 id="vision-dialog-title"></h2><button type="button" class="vision-dialog-close" aria-label="关闭愿景详情">关闭</button></header>'
               '<div class="vision-dialog-body"></div></dialog>' + cost_estimate(content) + policy_connections(content))
    out.append('<div class="vision-conclusion"><p>我们希望看到的成效，是学生能独立解决新问题、隔一段时间仍然会用，教师的调整有后续结果，家庭少一些无效投入。</p></div>')
    out.append('<div class="chapter-bridge"><div class="bridge-flow"><div class="bridge-output"><span>希望改变的教学日常</span>'
               '<strong>学生学习、教师教学、学校教研与社会支持</strong></div><div class="bridge-track" aria-hidden="true">'
               '<svg viewBox="0 0 180 32"><path d="M5 16H173m-7-6 7 6-7 6"/></svg><i class="bridge-packet"></i></div>'
               '<div class="bridge-input"><span>接下来说明</span><strong>系统怎样实现这些变化</strong></div></div>'
               '<a class="chapter-transition" href="#highlights" data-vision-skip>这些变化如何实现？从项目亮点开始'
               '<span>方法、时间、能力图谱与教学协同</span><svg viewBox="0 0 24 24" aria-hidden="true">'
               '<path d="M4 12h15m-6-6 6 6-6 6"/></svg></a></div></section>')
    return ''.join(out)
