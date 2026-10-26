(() => {
  'use strict';
  const GROUPS = [
    { id: 'representation', title: '教学表示与数据', hint: '课程内容怎样映射到解题操作与训练材料', chapters: ['overview', 'concepts', 'dataset'] },
    { id: 'single-task', title: '单题与诊断', hint: '一道题中的参考步骤、作答判断、教学和变式', chapters: ['single', 'diagnosis'] },
    { id: 'learning', title: '持续学习', hint: '错题、训练、考试和长期学习记录怎样连接', chapters: ['library', 'routines', 'exam', 'career'] },
    { id: 'collaboration', title: '教学协同', hint: '教师与学校怎样使用同一套学习依据', chapters: ['teacher', 'school', 'modes'] },
    { id: 'technology', title: '技术接入与演进', hint: 'Agent、MCP、反馈核验和版本改进', chapters: ['agent', 'mcp', 'evolution'] },
  ];
  const $ = selector => document.querySelector(selector);
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const paragraphs = (parent, values, className = '') => {
    const rows = Array.isArray(values) ? values : values ? [values] : [];
    for (const value of rows) parent.append(el('p', className, value));
  };
  const externalLink = (label, value) => {
    if (typeof value !== 'string' || !value.startsWith('https://')) return null;
    const link = el('a', '', label);
    link.href = value;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    return link;
  };
  const STATUS = {
    mixed: '已有基础与方案并存', prototype: '原型或设计方案', research: '研究方向',
    implemented: '已有业务实现', plan: '待接通的方案', planned: '待接通的方案',
  };
  const OLD_ANCHORS = {
    terms: 'concepts', time: 'diagnosis', longterm: 'career', research: 'single-task',
  };
  const localAnchor = value => {
    if (!value || !value.startsWith('#')) return '';
    const original = value.slice(1);
    const mapped = OLD_ANCHORS[original] || original;
    return `#${mapped}`;
  };

  function studyCard(study) {
    const article = el('article', 'study-card');
    article.append(el('h5', '', study.title || '研究来源'));
    const links = el('div', 'study-links');
    const site = externalLink('研究页面 ↗', study.website_url || study.url);
    const paper = externalLink('论文原文 ↗', study.paper_url || study.source_url);
    if (site) links.append(site);
    if (paper) links.append(paper);
    if (links.childElementCount) article.append(links);
    if (study.contribution) article.append(el('p', 'study-contribution', study.contribution));
    const fields = [
      ['研究任务', study.task], ['具体方法', study.method], ['研究结果', study.findings || study.response],
      ['研究范围', study.scope], ['对应的系统机制', study.response], ['对照验证', study.validation],
    ].filter(([, value]) => value);
    if (fields.length) {
      const grid = el('dl', 'study-facts');
      for (const [label, value] of fields) {
        const pair = el('div', '');
        pair.append(el('dt', label === '研究范围' ? 'study-scope' : '', label));
        pair.append(el('dd', '', value));
        grid.append(pair);
      }
      article.append(grid);
    }
    if (study.source_location || study.version) {
      article.append(el('p', 'study-citation', [study.version, study.source_location].filter(Boolean).join('；')));
    }
    return article;
  }

  function renderChapter(chapter) {
    const article = el('article', 'topic-article');
    article.id = chapter.id;
    const heading = el('h3', '', chapter.title || '项目主题');
    article.append(heading);
    if (chapter.thesis) article.append(el('p', 'topic-thesis', chapter.thesis));
    if (chapter.status) article.append(el('span', 'topic-status', STATUS[chapter.status] || chapter.status));
    if (chapter.pain) {
      const pain = el('aside', 'topic-pain');
      if (chapter.pain.title) pain.append(el('strong', '', chapter.pain.title));
      paragraphs(pain, chapter.pain.text);
      article.append(pain);
    }
    const copy = el('div', 'topic-copy topic-column');
    paragraphs(copy, chapter.body);
    if (copy.childElementCount) article.append(copy);
    if (chapter.mechanism?.length) {
      const list = el('ul', 'topic-mechanism');
      for (const item of chapter.mechanism) list.append(el('li', '', item));
      article.append(list);
    }
    if (chapter.bridge?.output || chapter.bridge?.input) {
      const connection = el('p', 'topic-bridge', [chapter.bridge.output, chapter.bridge.input].filter(Boolean).join(' ← '));
      article.append(connection);
    }
    if (chapter.details?.length) {
      const box = el('div', 'topic-details');
      for (const detail of chapter.details) {
        const disclosure = el('details', '');
        disclosure.append(el('summary', '', detail.title || '详细说明'));
        paragraphs(disclosure, detail.body);
        box.append(disclosure);
      }
      article.append(box);
    }
    if (chapter.research?.length) {
      const research = el('section', 'research-detail');
      research.append(el('h4', '', '相关研究与对照'));
      for (const study of chapter.research) research.append(studyCard(study));
      article.append(research);
    }
    return article;
  }

  function renderHighlights(parent, data) {
    const section = el('section', 'topic-group');
    section.id = 'project-highlights';
    const header = el('header', '');
    header.append(el('h2', '', data.label || '系统设计与研究特点'));
    header.append(el('p', '', data.title || ''));
    section.append(header);
    if (data.subtitle) section.append(el('p', 'topic-column', data.subtitle));
    for (const point of data.points || []) {
      const row = el('article', 'highlight-record');
      row.append(el('h3', '', point.label || ''));
      const content = el('div', '');
      content.append(el('p', 'highlight-title', point.title || ''));
      if (point.pain) content.append(el('p', 'highlight-pain', point.pain));
      paragraphs(content, point.body);
      if (point.key) content.append(el('p', 'topic-thesis', point.key));
      row.append(content);
      section.append(row);
    }
    if (data.manifesto) {
      const manifesto = el('div', 'vision-manifesto');
      manifesto.append(el('blockquote', '', data.manifesto));
      if (data.manifesto_en) manifesto.append(el('p', 'manifesto-translation', data.manifesto_en));
      section.append(manifesto);
    }
    parent.append(section);
  }

  function renderVision(parent, vision) {
    const section = el('section', 'topic-group');
    section.id = 'vision';
    const header = el('header', '');
    header.append(el('h2', '', vision.title || '教学愿景'));
    header.append(el('p', '', '以下内容描述目标形态；每项支撑功能的状态与证据链接已在相关专题说明。'));
    section.append(header);
    if (vision.headline) section.append(el('p', 'topic-thesis', vision.headline));
    paragraphs(section, vision.intro);
    paragraphs(section, vision.scope, 'vision-scope');
    const groupNames = { students: '学生', teachers: '教师', schools: '学校', society: '社会价值' };
    for (const group of vision.groups || []) {
      const disclosure = el('details', 'vision-group');
      const label = [groupNames[group.id] || group.title, group.tagline].filter(Boolean).join(' · ');
      disclosure.append(el('summary', '', `${label}：${group.summary || ''}`));
      for (const row of group.rows || []) {
        const line = el('article', 'vision-row');
        line.append(el('h4', '', row.aspect || ''));
        const before = el('p', '');
        before.append(el('strong', '', '常见困难'));
        before.append(document.createTextNode(row.before || ''));
        const after = el('p', '');
        after.append(el('strong', '', '希望的变化'));
        after.append(document.createTextNode(row.after || ''));
        line.append(before, after);
        disclosure.append(line);
        if (row.features?.length) {
          const links = el('div', 'vision-links');
          for (const feature of row.features) {
            const anchor = el('a', '', `${feature.label} · ${feature.status}`);
            anchor.href = localAnchor(feature.target) || '#project-highlights';
            links.append(anchor);
          }
          disclosure.append(links);
        }
      }
      section.append(disclosure);
    }
    if (vision.examples?.length) {
      const examples = el('div', 'vision-examples');
      examples.append(el('h3', '', '教学变化的具体例子'));
      for (const example of vision.examples) {
        const disclosure = el('details', 'topic-details');
        disclosure.append(el('summary', '', example.title || '案例'));
        paragraphs(disclosure, example.summary);
        for (const step of example.steps || []) {
          const card = el('section', 'vision-example-step');
          card.append(el('h4', '', step.title || ''));
          paragraphs(card, step.body);
          disclosure.append(card);
        }
        examples.append(disclosure);
      }
      section.append(examples);
    }
    if (vision.principles?.length) {
      const principles = el('div', 'vision-principles');
      principles.append(el('h3', '', '设计原则'));
      for (const principle of vision.principles) {
        const disclosure = el('details', 'topic-details');
        disclosure.append(el('summary', '', principle.title || '原則'));
        if (principle.before) paragraphs(disclosure, `常见做法：${principle.before}`);
        if (principle.after) paragraphs(disclosure, `期望方向：${principle.after}`);
        paragraphs(disclosure, principle.body);
        principles.append(disclosure);
      }
      section.append(principles);
    }
    if (vision.social_mechanism?.length) {
      const social = el('div', 'vision-principles');
      social.append(el('h3', '', '社会价值如何逐步产生'));
      for (const item of vision.social_mechanism) {
        const article = el('article', 'social-item');
        article.append(el('h4', '', item.title || ''));
        paragraphs(article, item.body);
        social.append(article);
      }
      section.append(social);
    }
    if (vision.evaluation) {
      const evaluation = el('aside', 'topic-pain');
      evaluation.append(el('strong', '', '如何评估实际收益'));
      paragraphs(evaluation, vision.evaluation);
      section.append(evaluation);
    }
    if (vision.policies?.length) {
      const policies = el('div', 'policy-list');
      policies.append(el('h3', '', '政策背景与范围'));
      for (const policy of vision.policies) {
        const disclosure = el('details', 'topic-details');
        disclosure.append(el('summary', '', policy.document || policy.title || '政策文件'));
        if (policy.mechanism) paragraphs(disclosure, `设计关联：${policy.mechanism}`);
        if (policy.scope) paragraphs(disclosure, `适用范围：${policy.scope}`);
        for (const [label, value] of [['文件原文', policy.url], ['转载页面', policy.mirror]]) {
          const link = externalLink(`${label} ↗`, value);
          if (link) disclosure.append(link, document.createTextNode(' '));
        }
        policies.append(disclosure);
      }
      section.append(policies);
    }
    parent.append(section);
  }

  function render(payload) {
    const target = $('#topic-catalog');
    const chapters = new Map((payload.chapters || []).map(chapter => [chapter.id, chapter]));
    for (const group of GROUPS) {
      const section = el('section', 'topic-group');
      section.id = group.id;
      const header = el('header', '');
      header.append(el('h2', '', group.title));
      header.append(el('p', '', group.hint));
      section.append(header);
      for (const id of group.chapters) {
        const chapter = chapters.get(id);
        if (chapter) section.append(renderChapter(chapter));
      }
      target.append(section);
    }
    renderHighlights(target, payload.highlights || {});
    renderVision(target, payload.vision || {});
    if (window.renderMathInElement) {
      window.renderMathInElement(target, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '$', right: '$', display: false },
        ],
        throwOnError: false,
        ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option'],
      });
    }
    target.setAttribute('aria-busy', 'false');
    $('#topic-load-status').textContent = '内容来自项目展示使用的核对版本；页面不会调用模型。';
  }

  fetch('/math-topics.json', { credentials: 'omit', cache: 'no-store' })
    .then(response => {
      if (!response.ok) throw new Error(`专题资料加载失败（HTTP ${response.status}）`);
      return response.json();
    })
    .then(render)
    .catch(error => {
      $('#topic-load-status').textContent = `${error.message}。请刷新页面重试。`;
      $('#topic-catalog').setAttribute('aria-busy', 'false');
    });
})();
