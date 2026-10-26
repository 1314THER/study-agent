#!/usr/bin/env python3
"""Build the public dataset atlas from audited aggregates, using stdlib only.

This generator never opens a database or copies question/student records.
dataset-data.json is the reviewable, dated source; HTML and provenance notes
are deterministic outputs. Run --check to verify sources and generated files.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "frontend/showcase"
DATA = PUBLIC / "dataset-data.json"
OUTPUT = PUBLIC / "dataset.html"
NOTES = ROOT / "docs/showcase-dataset-sources.md"


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def number(value: int) -> str:
    return f"{value:,}"


def source_link(source: str) -> str:
    # Provenance lives in the downloadable snapshot and generated audit notes.
    return ""


def badge(value: str, kind: str = "recorded") -> str:
    return f'<span class="data-status status-{esc(kind)}">{esc(value)}</span>'


def table(headers: list[str], rows: list[list[str]], caption: str, cls: str = "") -> str:
    head = "".join(f'<th scope="col">{esc(h)}</th>' for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>" for row in rows)
    return (f'<div class="table-scroll {esc(cls)}" tabindex="0" role="region" aria-label="{esc(caption)}">'
            f'<table><caption>{esc(caption)}</caption><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


def split_bar(items: list[dict[str, Any]], total: int, caption: str) -> str:
    segments = "".join(
        f'<span class="bar-{esc(x.get("tone", "pending"))}" '
        f'style="--share:{x["count"] / total * 100:.5f}%"></span>' for x in items)
    legend = "".join(
        f'<li><i class="bar-{esc(x.get("tone", "pending"))}" aria-hidden="true"></i>'
        f'<span>{esc(x["name"].replace(" complete", "").replace(" needs_review", "").replace(" deferred_graphic", ""))}</span><strong>{number(x["count"])}</strong>'
        f'<span class="percentage">{x["count"] / total * 100:.1f}%</span></li>' for x in items)
    return (f'<figure class="distribution"><figcaption>{esc(caption)}</figcaption>'
            f'<div class="split-bar" aria-hidden="true">{segments}</div><ul>{legend}</ul></figure>')


def validate(data: dict[str, Any]) -> None:
    assert data["schema_version"] == 1, "Unknown dataset schema"
    expected = {
        "schema_version", "title", "audit", "headline_metrics", "definitions", "inventory",
        "subjects", "step_types", "curriculum", "pool", "matching", "data_layers", "coverage",
        "scenarios", "target_flow", "sources", "public_data_policy",
    }
    assert set(data) == expected, "Unexpected public dataset fields"
    sources = {s["id"]: s for s in data["sources"]}
    assert len(sources) == len(data["sources"]), "Duplicate source ID"
    for entry in data["inventory"] + data["headline_metrics"]:
        assert isinstance(entry["value"], int) and entry["value"] >= 0
        assert entry["source"] in sources
    for source in data["sources"]:
        if source["kind"] == "repository":
            path = (ROOT / source["path"]).resolve()
            assert path.is_relative_to(ROOT) and path.is_file(), "Invalid repository source"
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            assert actual == source["sha256"], f'Source changed: {source["path"]}; re-audit before rebuilding'
    pool, matching = data["pool"], data["matching"]
    assert sum(x["count"] for x in pool["completeness"]) == pool["count"]
    assert sum(x["count"] for x in pool["types"]) == pool["count"]
    assert pool["year_known"] + pool["year_unknown"] == pool["count"]
    assert sum(x["count"] for x in matching["states"]) == matching["total"] == pool["count"]
    assert matching["high_confidence"] + matching["insufficient"] == matching["classified"]
    assert matching["review_pending"] + matching["review_accepted"] == matching["total"]
    assert data["audit"]["matching_state"] == "paused", "Update status copy when re-auditing"
    assert sum(x["knowledge"] for x in data["subjects"]) == 541
    assert sum(x["groups"] for x in data["subjects"]) == 100
    assert sum(x["routines"] for x in data["subjects"]) == 1019
    assert sum(x["parents"] for x in data["step_types"]) == 99
    assert sum(x["items"] for x in data["step_types"]) == 359
    assert sum(x["count"] for x in data["curriculum"]["relationships"]) == 4070
    catalog = json.loads((ROOT / "backend/routine_catalog.json").read_text())["routines"]
    assert len(catalog) == 1019
    for key, expected_count in (("key_steps", 3057), ("signals", 2326), ("exclusions", 1247), ("confusable_ids", 2305)):
        assert sum(len(x.get(key) or []) for x in catalog) == expected_count, key
    manifest = json.loads((PUBLIC / "question-bank/manifest.json").read_text())
    assert manifest["count"] == 2, "Re-audit public demonstration count"
    assert all(s["base"] > 0 and s["multiplier"] > 0 for s in data["scenarios"])
    text = json.dumps(data, ensure_ascii=False).lower()
    forbidden = ('"api_key"', '"password"', '"student_id"', '"account_id"', '"answer_json"', '"question_text"')
    assert not any(token in text for token in forbidden), "Private/raw fields in public aggregates"


def render(data: dict[str, Any]) -> str:
    audit, pool, matching = data["audit"], data["pool"], data["matching"]
    concepts = "".join(
        f'<article class="concept-definition"><h3>{esc(x["name"])}</h3>'
        f'<p>{esc(x["body"])}</p></article>' for x in data["definitions"])
    edges = ["讲授", "知识前置", "顺序组合", "应用于题目"]
    nodes = []
    for i, metric in enumerate(data["headline_metrics"]):
        nodes.append(f'<div class="atlas-node node-{esc(metric["key"])}"><span>{esc(metric["unit"])}</span>'
                     f'<strong>{number(metric["value"])}</strong><p>{esc(metric["label"])}</p>'
                     f'{source_link(metric["source"])}</div>')
        if i < 4:
            nodes.append(f'<div class="atlas-edge"><span>{edges[i]}</span><b aria-hidden="true">→</b></div>')
    public_names = {"已生成结构化prepared_json": "已完成结构化准备", "已建立正式题目关联": "已关联到正式题库"}
    inventory_rows = [
        [esc(x["layer"]), f'<strong>{esc(public_names.get(x["name"], x["name"]))}</strong>',
         f'<span class="table-number">{number(x["value"])}</span> <span class="unit">{esc(x["unit"])}</span>',
         badge(x["status"], "pending" if "待" in x["status"] or x["status"] == "草稿" else "recorded")]
        for x in data["inventory"]]
    inventory = table(["数据层", "对象", "数量", "阶段"], inventory_rows,
                      "按对象与建设阶段分别统计；题目、出处、方法引用和步骤实例各有自己的计数单位。", "inventory-table")
    subjects = table(["板块", "二级知识分类", "三级知识点", "套路目录"], [
        [esc(x["label"]), number(x["groups"]), number(x["knowledge"]), number(x["routines"])]
        for x in data["subjects"]], "知识点与套路按12个板块分别统计；列数反映各自定义，不表示逐条映射已完成。")
    steps = table(["题型作用域", "一级步骤", "二级具体步骤", "词表状态"], [
        [esc(x["name"]), number(x["parents"]), number(x["items"]),
         badge(x["status"], "recorded" if x["items"] else "pending")]
        for x in data["step_types"]], "12个题型槽位中，7类已有步骤词表，5类仍待补写。")
    graph_entities = table(["图谱实体", "有效记录"], [
        [esc(x["name"]), number(x["count"])] for x in data["curriculum"]["entities"]], "课时图谱的有效教学节点，当前处于草稿建设阶段。")
    graph_relations = table(["关系", "草稿记录"], [
        [esc(x["name"]), number(x["count"])]
        for x in data["curriculum"]["relationships"]], "4,070条教学关系，连接课时、知识、解法与套路。")
    pool_types = table(["题型标签", "题目数"], [
        [esc(x["name"]), number(x["count"])] for x in pool["types"]], "题池题型标注：未知类型保留为未知，不根据题面猜填。")
    layers = "".join(
        f'<article class="layer-row"><div><h3>{esc(x["title"])}</h3><p>{esc(x["objects"])}</p></div>'
        f'<div><span class="column-label">已有数据</span><p>{esc(x["current"])}</p></div>'
        f'<div><span class="column-label target-label">贯通目标</span><p>{esc(x["target"])}</p></div></article>'
        for x in data["data_layers"])
    coverage = table(["需要连接的对象", "当前依据", "全量贯通需要补齐", "阶段"], [
        [f'<strong>{esc(x["link"])}</strong>', esc(x["current"].replace("prepared_json与formal_question_id均为0。", "题池的全量结构化准备与正式导入待建设。")), esc(x["next"]), badge(x["status"], "pending")]
        for x in data["coverage"]], "关系覆盖清单：对象数量、关联记录与通过审核的关系分别判断。", "coverage-table")
    scenario_meanings = [
        "每条实例步骤保存具体推导、知识引用与本题难度，支撑步骤批改、分步教学和局部训练。",
        "适配标准解答、详细讲解等不同阅读需要，为每个讲解版本保留核验与来源。",
        "围绕原题的方法改变条件，经过重解、去重和审核，组织针对性的迁移训练。",
        "为每项套路配置母题和变式角色，继续延展到独立练习、迁移与延迟复查。",
    ]
    scenarios = "".join(
        f'<article class="scenario"><div class="scenario-heading">{badge("规划测算", "target")}<h3>{esc(x["name"])}</h3></div>'
        f'<div class="scenario-equation"><span>{number(x["base"])} × {number(x["multiplier"])}</span>'
        f'<b aria-hidden="true">=</b><strong>{number(x["base"] * x["multiplier"])}</strong><span>{esc(x["unit"])}</span></div>'
        f'<p class="scenario-assumption">{esc(x["assumption"])}</p><p>{esc(meaning)}</p></article>'
        for x, meaning in zip(data["scenarios"], scenario_meanings))
    target = "".join(
        f'<li><h3>{esc(x["title"])}</h3><p>{esc(x["body"])}</p></li>' for x in data["target_flow"])
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="StudyAgent数据集详细统计：329课时、541知识点、359具体步骤、1019项套路目录与23261道入池素材的结构、匹配状态和规划测算。">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#080808">
<title>数据集详细统计 · StudyAgent</title>
<link rel="icon" type="image/png" sizes="64x64" href="/showcase/assets/fudan-favicon-white.png">
<link rel="apple-touch-icon" href="/showcase/assets/fudan-emblem-white.png">
<link rel="stylesheet" href="/showcase/dataset.css">
</head>
<body class="dataset-page">
<a class="skip-link" href="#main-content">跳到数据集内容</a>
<header class="dataset-header"><a class="dataset-brand" href="/home.html#dataset"><img src="/showcase/assets/fudan-emblem-white.png" width="44" height="44" alt="复旦大学校徽"><span>StudyAgent<small>数据集详细统计</small></span></a><nav aria-label="数据集统计导航"><a href="#inventory">完整规模</a><a href="#matching">匹配状态</a><a href="#target">全量图景</a><a href="/home.html#dataset">返回数据集</a></nav></header>
<main id="main-content">
<header class="dataset-intro"><p class="breadcrumb"><a href="/home.html#dataset">数据集</a><span aria-hidden="true"> / </span> 详细统计</p><h1>数据集详细统计</h1><p class="intro-thesis">按教学词表、课时图谱、题目素材与匹配进度展开完整统计，保留各类数据的建设阶段与全量测算条件。</p><div class="audit-strip"><span>建设快照 <time datetime="{esc(audit['date'])}">{esc(audit['date'])}</time></span><span>高中数学</span><a href="/showcase/dataset-data.json">下载规模快照</a></div></header>
<section class="atlas-section" id="concepts" aria-labelledby="concepts-title"><div class="section-heading"><h2 id="concepts-title">先分清对象，再看数量</h2><p>前置关系与实例应用，共用一套教学语言。</p></div><figure class="concept-atlas"><div class="atlas-flow">{''.join(nodes)}</div><figcaption>前三条箭头表示概念上的教学前置与组合，最后一条表示方法应用。它们不是一一对应关系，也不代表数据库已完成全量映射。题池数字表示已收集素材。</figcaption></figure><div class="concept-definitions">{concepts}</div><aside class="semantic-note"><strong>标准步骤 ≠ 实例步骤；母题类 ≠ 母题示例题。</strong><p>359条具体步骤是可复用的操作词表。一道题实际用了哪些操作、怎样推导和计算，需要另存为本题的实例步骤；1,019个套路目录项描述方法结构，不等于1,019道题。</p><a href="/home.html#single">继续看这些结构如何支持单题功能</a></aside></section>
<section id="target" aria-labelledby="target-title"><div class="section-heading"><h2 id="target-title">全量贯通后的数据图景</h2><p>以现有题池和目录为基数，按以下假设测算建设规模。每项均为规划目标。</p></div><div class="scenario-grid">{scenarios}</div><div class="subsection-heading"><h3>规模最终转为五种教学能力</h3><p>题目有出处，步骤可检查，方法可检索，训练可组织，学习变化可追踪。</p></div><ol class="target-flow">{target}</ol><div class="target-return"><p>从一份错答出发，找到本题步骤、对应操作与知识准备，安排整题训练或局部补练，再通过新的独立作答观察学习变化。</p><a href="/home.html#single">继续看单题能力，理解这些数据怎样服务学习</a></div></section>
<section id="inventory" aria-labelledby="inventory-title"><div class="section-heading"><h2 id="inventory-title">所有数量放回各自的数据层</h2><p>已记录的对象、候选关联与正式训练，分别保留自己的口径。</p></div>{inventory}</section>
<section id="structure" aria-labelledby="structure-title"><div class="section-heading"><h2 id="structure-title">覆盖高中数学的内容与方法</h2><p>按知识板块组织内容，按题型组织步骤，按课时连接教学。</p></div><div class="paired-tables"><article><h3>知识点与套路目录</h3>{subjects}</article><article><h3>步骤按题型组织</h3>{steps}</article></div><div class="subsection-heading"><h3>课时图谱：把内容组织成教学路径</h3><p>174个教学知识实体、288个套路实体和234个解法实体，连接课堂讲授、前置准备与同步练习。</p></div><div class="paired-tables graph-tables">{graph_entities}{graph_relations}</div></section>
<section id="pool" aria-labelledby="pool-title"><div class="section-heading"><h2 id="pool-title">23,261道题，汇入同一素材池</h2><p>保留题目、出处、原材料完整性与题型，逐步转成可检索的教学内容。</p></div><div class="pool-overview"><div class="pool-statement"><strong>{number(pool['count'])}</strong><span>道去重入池素材</span><p>来自{number(pool['sources'])}个来源，保留{number(pool['occurrences'])}条出处记录。同一道题可以关联多个出处。</p></div>{split_bar(pool['completeness'], pool['count'], '原材料整理进度')}</div><div class="paired-tables"><article>{pool_types}</article><article class="year-coverage"><h3>年份信息</h3><p><strong>{number(pool['year_known'])}</strong>道素材有年份标签，已记录年份跨度为{pool['year_min']}—{pool['year_max']}年。</p><p>其余<strong>{number(pool['year_unknown'])}</strong>道素材将继续补充年份与来源信息，便于按课程、方法与考试情境检索。</p></article></div></section>
<section id="matching" aria-labelledby="matching-title"><div class="section-heading"><h2 id="matching-title">从题池走向套路：匹配建设进度</h2><p>先找到可能的方法归属，再确认适用条件与步骤结构，最后组织训练。</p></div><div class="batch-status">{badge('批次暂停快照', 'pending')}<p>保存进度：<time datetime="2026-10-25T11:58:47+08:00">2026-10-25 11:58:47 +08:00</time></p></div>{split_bar(matching['states'], matching['total'], '当前23,261道素材的匹配状态')}<div class="candidate-breakdown"><article><span class="column-label">已分类 {number(matching['classified'])} 道</span><div class="candidate-values"><div><strong>{number(matching['high_confidence'])}</strong><h3>高置信主套路候选</h3><p>已找到主套路候选，进入人工确认环节。</p></div><div><strong>{number(matching['insufficient'])}</strong><h3>资料不足 / 低置信</h3><p>补充材料与判断依据后继续处理。</p></div></div></article><article class="coverage-summary"><span class="column-label">候选覆盖</span><p class="coverage-fraction"><strong>{number(matching['covered_routines'])}</strong><span>/ 1,019 项套路目录</span></p><p>已出现高置信候选的套路范围。</p><p><strong>人工审核通过 {matching['review_accepted']} 道；全部候选仍待确认。</strong></p></article></div></section>
<section id="layers" aria-labelledby="layers-title"><div class="section-heading"><h2 id="layers-title">数据分层之后，才能连成教学流程</h2><p>题目是谁、解法是什么、学生这一次做得怎样，分别存储并通过关系连接。</p></div><div class="data-layers">{layers}</div><div class="semantic-note"><strong>同一道题可以有多次作答、多种成立解法和多个讲解版本。</strong><p>一次提示后完成与一次无提示新题完成，证据含义不同。后续生涯记录应引用题目和解析版本，不把题库规模直接换算成学生掌握程度。</p><a href="/home.html#career">返回生涯与能力评估设计</a></div></section>
<section id="coverage" aria-labelledby="coverage-title"><div class="section-heading"><h2 id="coverage-title">全量贯通，还需要完成哪些连接</h2><p>已有数量提供起点，关系对齐、人工核验和版本维护决定这些数据能否被可靠复用。</p></div>{coverage}</section>
<section class="data-scope" aria-labelledby="scope-title"><div class="section-heading"><h2 id="scope-title">数据口径</h2></div><ul><li>本页按2026-10-25的词表、目录和本地聚合快照展示数量。</li><li>目录描述方法，题池收集素材，候选等待确认，可训练内容按正式训练角色统计。</li><li>标准步骤是可复用操作；实例步骤是操作在一道具体题中的应用。</li><li>规划测算保留乘数假设，参考解析版本、步骤实例和训练题位分别计数。</li></ul></section>
</main>
<footer class="dataset-footer"><div class="dataset-footer-brand"><img src="/showcase/assets/fudan-emblem-white.png" width="44" height="44" alt=""><div><strong>StudyAgent</strong><p>让每次作答，成为下一步学习的依据。</p></div></div><nav aria-label="相关网站"><a href="https://150.chat/" target="_blank" rel="noopener noreferrer">正式站首页</a><a href="https://150.chat/home.html" target="_blank" rel="noopener noreferrer">学习系统</a><a href="https://github.com/1314THER/study-agent" target="_blank" rel="noopener noreferrer">代码与研究文档</a><a href="/home.html#dataset">返回数据集</a></nav><p class="site-registration"><a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">渝ICP备2026024246号-1</a></p></footer>
</body></html>
'''


def render_notes(data: dict[str, Any]) -> str:
    lines = [
        "# 展示站数据集页面：来源、口径与更新方法", "",
        "> 此文件由 `scripts/build_showcase_dataset.py` 根据公开聚合JSON生成。", "",
        "页面：`/showcase/dataset.html`。输入：`frontend/showcase/dataset-data.json`。",
        "页面定位为数据集详细统计；主体数据集嵌入项目介绍的`#dataset`章节，详情页的返回入口均指向该章节。",
        "生成器仅使用Python标准库，不打开数据库、不调用模型、不导出题干或个人记录。", "",
        "## 核对范围", "", data["audit"]["scope"], "",
        f'核对时间：{data["audit"]["checked_at"]}。{data["audit"]["method"]}', "",
        "设计页面前完整阅读了《项目名词与教学关系定义》及《当前实现能力与名词数量》。后者的原数量为2026-10-24快照；本页以2026-10-25只读聚合更新数量，保留其实现边界。", "",
        "数据库聚合由同一任务内的footer_metadata审计提供；本页只接收计数和口径，不接收原始题目、学生作答或账号数据。", "",
        "## 文件来源与版本", "", "| 依据 | 路径 | SHA-256 |", "| --- | --- | --- |",
    ]
    for source in data["sources"]:
        lines.append(f'| {source["title"]} | `{source["path"]}` | {source.get("sha256", "仅聚合，不分发数据库")} |')
    lines += ["", "## 数量与作用域", "", "| 层 | 对象 | 数量 | 口径 |", "| --- | --- | --- | --- |"]
    for row in data["inventory"]:
        lines.append(f'| {row["layer"]} | {row["name"]} | {number(row["value"])}{row["unit"]} | {row["note"]} |')
    lines += [
        "", "## 只读聚合依据", "",
        "- 课时图谱：`cw_entities WHERE active=1 GROUP BY kind,status`；`cw_edges GROUP BY kind,status`。上述4070条为draft，另2条rejected不计。",
        "- 原题池：`pool_items`计去重题目；按`completeness`、`question_type`、`year`分组；年份空值及空串均计未知。`pool_occurrences`计出处，`pool_sources`计来源。",
        "- 准备情况：`pool_items.prepared_json`与`formal_question_id`非空数量各为0；不能用原材料complete状态替代结构化准备。",
        "- 匹配状态：筛选当前批次的`review_items`，按`status`、`review_status`分组；classified中另检查`primary_id`与`confidence`。5813为有主套路的高置信候选，4703为资料不足/低置信，两者合为10516。",
        "- 当前匹配run状态为paused，更新时间2026-10-25 11:58:47 +08:00；不采用较早progress.json中的running缓存。",
        "- 本地业务：`questions`33条，`question_steps`147条；33份有效answer_json中子问步骤求和也为147。这里只保存聚合，不公开answer_json。",
        "- 正式训练：29个定义；25项有母题关联；1项有母题及variant1/2/3全部角色关联并核对关联题目存在，仍须业务核验。",
        "- 公开演示：question-bank清单2道全国卷；8份保存管线记录。与23261道内部题池分别计数。", "",
        "## 候选匹配与素材状态", "", "| 状态 | 数量 |", "| --- | --- |",
    ]
    for state in data["matching"]["states"]:
        lines.append(f'| {state["name"]}（{state["key"]}） | {number(state["count"])} |')
    lines += ["", "人工审核pending：23261；通过：0。候选涉及554个目录套路，不能描述为554个已经完成训练的套路。", ""]
    for state in data["pool"]["completeness"]:
        lines.append(f'- {state["name"]}：{number(state["count"])}。')
    lines += ["", "## 全量规划测算", "", "| 测算 | 假设 | 结果 |", "| --- | --- | --- |"]
    for scenario in data["scenarios"]:
        result = scenario["base"] * scenario["multiplier"]
        lines.append(f'| {scenario["name"]} | {scenario["assumption"]} | {number(scenario["base"])} × {scenario["multiplier"]} = {number(result)}{scenario["unit"]} |')
    lines += [
        "", "以上均为规划假设，不是当前已有数量；不同对象不相加。解析风格版本不等于不同解法；候选变式须去重并核验；角色位不等于独立题目数。", "",
        "## 公开范围", "", data["public_data_policy"], "",
        "62个素材来源publication_allowed均为false；页面不能从内部题池导出题干、原解析或题图。公开演示仍以独立清单为准。", "",
        "## 更新与校验", "", "```sh", "python3 scripts/build_showcase_dataset.py", "python3 scripts/build_showcase_dataset.py --check", "```", "",
        "更新时重新做只读聚合，修改dataset-data.json中的数量、时间、口径和相关文件哈希，再运行生成器。--check验证分组总和、固定词表总量、目录字段数量、公开演示清单、来源文件哈希和生成结果一致性。", "",
        "dataset.css为手工维护的独立样式，无远程字体、脚本、模型请求或业务接口调用。所有正文静态可读，不使用details折叠。", "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check sources and deterministic outputs without writing")
    args = parser.parse_args()
    data = json.loads(DATA.read_text(encoding="utf-8"))
    validate(data)
    outputs = {OUTPUT: render(data), NOTES: render_notes(data)}
    failures = []
    for path, expected in outputs.items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                failures.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(expected, encoding="utf-8")
    if failures:
        raise SystemExit("Stale generated dataset files: " + ", ".join(failures))
    print(json.dumps({"ok": True, "mode": "check" if args.check else "build",
                      "inventory_rows": len(data["inventory"]), "sources": len(data["sources"]),
                      "question_pool": data["pool"]["count"], "matching_state": data["audit"]["matching_state"],
                      "outputs": [str(p.relative_to(ROOT)) for p in outputs]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
