"""Build the readable research walkthrough from reviewed chapter content.

No model calls or private database access. The source map is checked before a
chapter is published so edits to its Markdown cannot silently go unnoticed.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'frontend/showcase'
IDS = ['overview', 'concepts', 'dataset', 'single', 'diagnosis', 'library', 'routines',
       'exam', 'career', 'agent', 'teacher', 'school', 'modes', 'mcp', 'evolution']
STATUS = {'implemented': '已有实现', 'prototype': '设计方案', 'research': '研究方向', 'mixed': '已有基础'}
NAV_LABELS = {'overview': '项目总览', 'concepts': '基础表示', 'dataset': '数据集', 'single': '单题能力',
              'diagnosis': '过程诊断', 'library': '错题与题库', 'routines': '套路训练', 'exam': '试卷维度',
              'career': '生涯评估', 'agent': '教学 Agent', 'teacher': '教师端', 'school': '学校端',
              'modes': '教学模式', 'mcp': 'MCP 适配', 'evolution': '自进化'}


def esc(value):
    return html.escape(str(value), quote=True)


def validate_source_map(content, mapping):
    """Fail closed if any chapter no longer matches its fully read sources."""
    rows = mapping.get('chapters', [])
    if [row.get('id') for row in rows] != IDS:
        raise ValueError('Source map must cover all fifteen chapters in order')
    if len({source['file'] for row in rows for source in row.get('sources', [])}) != mapping.get('source_count'):
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


def paragraphs(value):
    return ''.join('<p>' + esc(row) + '</p>' for row in (value if isinstance(value, list) else [value]) if row)


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
<label>查找题目<input id="bank-search" type="search" placeholder="题干、板块、全国卷来源"></label>
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
    out = ['<section class="research-notes" aria-label="相关研究与本项目的关系"><h3>研究对照</h3>']
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
                out.append('<div><h5>' + title + '</h5>' + paragraphs(row[key]) + '</div>')
        if row.get('source_location'):
            out.append('<p class="research-location">' + esc(row['source_location']) + '</p>')
        out.append('</div><div class="research-project"><span class="research-side-label">StudyAgent</span>')
        for key, title in [('response', '对应的系统机制'), ('validation', '对照验证')]:
            if row.get(key):
                out.append('<div><h5>' + title + '</h5>' + paragraphs(row[key]) + '</div>')
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


def dataset_markup():
    data = json.loads((PUBLIC / 'dataset-data.json').read_text())
    metrics = ''.join('<div class="dataset-metric"><dt>' + esc(row['unit']) + '</dt><dd>' + format(row['value'], ',') + '<p>' + esc(row['label']) + '</p></dd></div>' for row in data['headline_metrics'])
    flow = ''.join('<article><span>' + str(i + 1).zfill(2) + '</span><h3>' + title + '</h3><p>' + text + '</p></article>' for i, (title, text) in enumerate([
        ('整理题目素材', f"{data['pool']['count']:,}道题，保留{data['pool']['occurrences']:,}条出处记录，来自{data['pool']['sources']}个来源。"),
        ('连接方法结构', f"{data['matching']['high_confidence']:,}道高置信主套路候选，涉及{data['matching']['covered_routines']}项套路目录，进入人工确认环节。"),
        ('支持教学应用', '题目经结构化解析与核验，连接步骤批改、分步教学、变式与练习组织。')]))
    goals = ''.join('<article><header><span>规划测算</span><h4>' + esc(row['name']) + '</h4></header><strong>' + format(row['base'] * row['multiplier'], ',') + '<small>' + esc(row['unit']) + '</small></strong><p>' + format(row['base'], ',') + ' × ' + str(row['multiplier']) + '。' + esc(row['assumption']) + '</p></article>' for row in data['scenarios'])
    return '<div class="inline-dataset"><dl class="inline-dataset-metrics">' + metrics + '</dl><div class="inline-dataset-flow">' + flow + '</div><div class="inline-dataset-target"><h3>全量贯通后的数据图景</h3><p>以当前题池和目录为基数，按以下假设测算建设规模。</p><div class="inline-dataset-goals">' + goals + '</div></div><div class="inline-dataset-footer"><span>建设快照 · ' + esc(data['audit']['date']) + '</span><a href="/showcase/dataset.html">查看详细统计 ↗</a></div></div>'


def build(content):
    chapters = content['chapters']
    if [c['id'] for c in chapters] != IDS:
        raise ValueError('All fifteen reviewed chapters must retain their order')
    nav = ''.join('<a href="#' + c['id'] + '"><span>' + str(i + 1).zfill(2) + '</span>' + esc(NAV_LABELS[c['id']]) + '</a>' for i, c in enumerate(chapters))
    primary_nav = ''.join('<a href="#' + c['id'] + '" title="' + esc(c['title']) + '">' + esc(NAV_LABELS[c['id']]) + '</a>' for c in chapters)
    sections = []
    aliases = {'single': ['solution', 'grading', 'teaching', 'generation', 'geometry'], 'routines': ['graph'], 'library': ['pool'], 'evolution': ['progress', 'research']}
    for i, chapter in enumerate(chapters):
        key = chapter['id']
        status = chapter['status']
        out = [''.join('<span id="' + a + '" class="anchor-alias" aria-hidden="true"></span>' for a in aliases.get(key, []))]
        out.append('<section class="chapter chapter-' + key + '" id="' + key + '" data-chapter="' + key + '" aria-labelledby="heading-' + key + '">')
        out.append('<header class="chapter-head"><div class="chapter-position"><span>' + str(i + 1).zfill(2) + '</span><span class="status status-' + status + '">' + STATUS[status] + '</span><span class="chapter-topic">' + esc(NAV_LABELS[key]) + '</span></div>')
        out.append('<h' + ('1' if i == 0 else '2') + ' id="heading-' + key + '">' + esc(chapter['title']) + '</h' + ('1' if i == 0 else '2') + '><p class="chapter-thesis">' + esc(chapter['thesis']) + '</p></header>')
        if chapter.get('pain'):
            out.append('<div class="pain-point"><span>现实痛点</span><h3>' + esc(chapter['pain']['title']) + '</h3>' + paragraphs(chapter['pain']['text']) + '</div>')
        scene = '<div id="scene-' + key + '" class="chapter-scene" aria-label="' + esc(chapter['title']) + '图解与演示">' + (bank_markup() if key == 'library' else dataset_markup() if key == 'dataset' else '<p class="scene-loading">正在准备交互图解…</p>') + '</div>'
        if key == 'overview':
            out.append(scene)
        out.append('<div class="chapter-copy-grid"><div class="chapter-main"><div class="chapter-prose">' + paragraphs(chapter.get('body', [])) + '</div>')
        if key != 'overview':
            out.append(scene)
        out.append('</div>')
        if chapter.get('details'):
            out.append('<aside class="chapter-marginalia" aria-label="设计批注">')
            for number, detail in enumerate(chapter['details'], 1):
                out.append('<div class="margin-note"><span class="note-number">' + str(number).zfill(2) + '</span><h3>' + esc(detail['title']) + '</h3>' + paragraphs(detail['body']) + '</div>')
            out.append('</aside>')
        out.append('</div>')
        out.append(references(chapter))
        if chapter.get('transition'):
            next_id = chapters[i + 1]['id'] if i + 1 < len(chapters) else 'overview'
            bridge = chapter.get('bridge', {'output': chapter['title'], 'input': chapters[(i + 1) % len(chapters)]['title']})
            out.append('<div class="chapter-bridge"><div class="bridge-flow"><div class="bridge-output"><span>这一章留下</span><strong>' + esc(bridge['output']) + '</strong></div><div class="bridge-track" aria-hidden="true"><svg viewBox="0 0 180 32"><path d="M5 16H173m-7-6 7 6-7 6"/></svg><i class="bridge-packet"></i></div><div class="bridge-input"><span>进入下一环</span><strong>' + esc(bridge['input']) + '</strong></div></div><a class="chapter-transition" href="#' + next_id + '">' + esc(chapter['transition']) + '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h15m-6-6 6 6-6 6"/></svg></a></div>')
        out.append('</section>')
        sections.append(''.join(out))
    return '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="StudyAgent 科研项目：以全国卷真实案例，讨论步骤诊断、方法迁移、长期学习证据与教学协同。">
<meta name="theme-color" content="#080808"><meta name="color-scheme" content="dark"><title>步骤诊断与方法迁移 · StudyAgent 科研展示</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%23242424'/%3E%3Ctext x='7' y='24' fill='white' font-size='25'%3EΣ%3C/text%3E%3C/svg%3E">
<link rel="stylesheet" href="/style.css"><link rel="stylesheet" href="/vendor/katex/katex.min.css"><link rel="stylesheet" href="/showcase/style.css"><link rel="stylesheet" href="/showcase/handwriting.css"><link rel="stylesheet" href="/showcase/transitions.css">
<script defer src="/vendor/katex/katex.min.js"></script><script defer src="/dimchart.js"></script><script defer src="/radar.js"></script><script defer src="/showcase/handwriting.js"></script><script defer src="/showcase/bank.js"></script><script defer src="/showcase/app.js"></script><script defer src="/showcase/transitions.js"></script>
</head><body class="research-showcase"><a class="skip-link" href="#main-content">跳到项目内容</a>
<header class="site-header"><a class="research-brand" href="#overview"><span class="brand-symbol" aria-hidden="true">∑</span><span>成为数学高手<small>StudyAgent 科研项目</small></span></a>
<nav class="primary-nav" aria-label="章节导航">''' + primary_nav + '''</nav>
<button id="contents-toggle" type="button" aria-expanded="false" aria-controls="chapter-contents">章节目录<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 7 5 5 5-5"/></svg></button></header>
<nav id="chapter-contents" class="chapter-contents" aria-label="完整章节目录" hidden>''' + nav + '''</nav>
<main id="main-content"><div class="page-intro"><span>高中数学 / 过程诊断 / 方法迁移</span><span>全国卷案例 · 从作答到教学</span></div>
<p id="demo-status" class="page-status" role="alert" hidden></p>''' + ''.join(sections) + '''</main>
<footer class="site-footer"><div><strong>StudyAgent</strong><p>让每次作答，成为下一步学习的依据。</p></div><div><a href="https://150.chat/" target="_blank" rel="noopener noreferrer">正式站首页</a><a href="https://150.chat/home.html" target="_blank" rel="noopener noreferrer">学习系统</a><a href="https://github.com/1314THER/study-agent" target="_blank" rel="noopener noreferrer">代码与研究文档</a><a href="#overview">回到系统总览</a></div><p class="site-registration"><a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">渝ICP备2026024246号-1</a></p><p class="site-author">项目负责人：施棋智<br>email：<a href="mailto:qzshi25@m.fudan.edu.cn">qzshi25@m.fudan.edu.cn</a></p></footer>
<dialog id="opening-dialog" class="opening-dialog" aria-labelledby="opening-title">
<svg class="opening-space" viewBox="0 0 1600 1000" preserveAspectRatio="xMidYMid slice" aria-hidden="true"><defs><radialGradient id="opening-haze"><stop stop-color="#565656" stop-opacity=".3"/><stop offset=".5" stop-color="#303030" stop-opacity=".15"/><stop offset="1" stop-color="#080808" stop-opacity="0"/></radialGradient><linearGradient id="opening-grid-fade" x2="0" y2="1"><stop stop-color="white" stop-opacity="0"/><stop offset=".4" stop-color="white" stop-opacity=".7"/><stop offset="1" stop-color="white" stop-opacity=".15"/></linearGradient><mask id="opening-grid-mask"><rect width="1600" height="1000" fill="url(#opening-grid-fade)"/></mask><linearGradient id="opening-orbit-light"><stop stop-color="#aaaaaa" stop-opacity="0"/><stop offset=".5" stop-color="#aaaaaa" stop-opacity=".35"/><stop offset="1" stop-color="#aaaaaa" stop-opacity="0"/></linearGradient></defs><ellipse cx="700" cy="480" rx="920" ry="590" fill="url(#opening-haze)"/><g class="opening-coordinate-grid" mask="url(#opening-grid-mask)" fill="none" stroke="#b8b8b8" stroke-width="1"><path d="M-800 1000L1060 470M-450 1000L1060 470M-100 1000L1060 470M250 1000L1060 470M600 1000L1060 470M950 1000L1060 470M1300 1000L1060 470M1650 1000L1060 470M2000 1000L1060 470M2350 1000L1060 470M2700 1000L1060 470M0 498H1600M0 523H1600M0 559H1600M0 611H1600M0 685H1600M0 791H1600M0 943H1600"/></g><g class="opening-orbits" transform="rotate(-18 1000 510)" fill="none"><ellipse cx="1000" cy="510" rx="720" ry="230" stroke="url(#opening-orbit-light)"/><ellipse cx="1000" cy="510" rx="780" ry="270" stroke="#808080" stroke-opacity=".1"/><path class="opening-signal" d="M280 510a720 230 0 0 1 1440 0" stroke="#d0d0d0" stroke-opacity=".65" stroke-width="1.5" pathLength="1"/><circle cx="1720" cy="510" r="3" fill="#e0e0e0" fill-opacity=".7"/></g></svg>
<div id="opening-animation"><header class="opening-masthead"><h2 id="opening-title" class="opening-title" tabindex="-1">study-agent项目介绍页面</h2></header><div class="opening-artwork"><img src="/showcase/launch-lettering.svg" width="685" height="355" alt="数学 · love"></div><div class="opening-entry"><button id="opening-enter" type="button"><span>点击进入预览</span><span class="opening-enter-icon" aria-hidden="true"><svg viewBox="0 0 32 24" fill="none"><path d="M2 12h27M22 5l7 7-7 7"/></svg></span></button></div><nav class="opening-related-links" aria-label="相关网站与备案"><a href="https://150.chat/" target="_blank" rel="noopener noreferrer">StudyAgent 正式站</a><a href="https://150.chat/home.html" target="_blank" rel="noopener noreferrer">学习系统</a><a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">渝ICP备2026024246号-1</a></nav><div class="opening-author"><span>项目负责人：施棋智</span><span>email：<a href="mailto:qzshi25@m.fudan.edu.cn">qzshi25@m.fudan.edu.cn</a></span></div></div></dialog>
<aside id="annotation-panel" class="annotation-panel" aria-label="补充批注" hidden><header><h2 id="annotation-title"></h2><button id="annotation-close" type="button" aria-label="关闭批注">×</button></header><div id="annotation-body"></div></aside>
<noscript><style>.chapter-scene:not(:has(.native-workbench)):not(#scene-dataset){display:none}</style><p class="noscript-note">正文、逻辑图、数据集与研究对照可直接阅读。</p></noscript>
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
    print('Verified fifteen research chapters' if args.check else 'Built fifteen research chapters')


if __name__ == '__main__':
    main()
