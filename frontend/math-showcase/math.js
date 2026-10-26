(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const math = node => {
    if (window.renderMathInElement) {
      window.renderMathInElement(node, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '$', right: '$', display: false },
        ],
        throwOnError: false,
        ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option'],
      });
    }
  };
  const textBlock = (tag, className, value) => {
    const node = el(tag, className, value || '');
    return node;
  };

  function diagnosis(root, data) {
    root.replaceChildren();
    const summary = el('p', 'diagnosis-overview', data.is_correct === false
      ? '这份作答未通过检查。正式批改返回中，第一步与后续步骤分别标明了原文依据。'
      : '正式批改记录已载入。');
    root.append(summary);
    for (const [index, step] of (data.steps || []).entries()) {
      const card = el('section', 'diagnosis-step' + (index ? ' is-dependent' : ''));
      const heading = el('h4', '', `步骤 ${step.step_number || index + 1} · ${step.title || '解题步骤'}`);
      const evidence = step.answer_evidence ? el('p', 'evidence-quote', `作答依据：“${step.answer_evidence}”`) : null;
      const detail = step.error_detail || step.comment || '';
      const explanation = detail ? el('p', '', detail) : null;
      const state = el('p', 'diagnosis-state', index ? '后续推导：结果依赖前一步' : '首个问题：计算错误');
      card.append(heading);
      if (evidence) card.append(evidence);
      if (explanation) card.append(explanation);
      card.append(state);
      root.append(card);
      math(card);
    }
  }

  function comparisons(root, items) {
    root.replaceChildren();
    const disclosure = el('details', '');
    disclosure.append(el('summary', '', '查看两种对照条件'));
    const content = el('div', 'comparison-grid');
    for (const record of items || []) {
      const box = el('section', '');
      box.append(el('h4', '', record.label));
      box.append(el('p', 'comparison-boundary', record.label === '常见使用方式'
        ? '题目与作答输入通用模型；系统使用正式批改流程。'
        : '通用模型与系统流程获得相同可用信息。'));
      box.append(el('div', 'comparison-output', record.content || '此条件暂无保存结果。'));
      content.append(box);
      math(box);
    }
    disclosure.append(content);
    root.append(disclosure);
  }

  function teaching(root, data) {
    root.replaceChildren();
    const frames = data.frames || [];
    const current = frames.find(frame => frame.input === 'C=π/3') || frames[1] || frames[0];
    if (current) {
      const summary = el('div', 'teaching-summary');
      summary.append(el('p', 'frame-count', `教学回放 · ${current.index} / ${frames.length}`));
      summary.append(el('blockquote', '', current.output));
      root.append(summary);
      math(summary);
    }
    const full = el('details', '');
    full.append(el('summary', '', `浏览全部 ${frames.length} 轮保存状态`));
    const list = el('ol', 'frame-list');
    for (const frame of frames) {
      const row = el('li', '');
      const input = frame.input ? `学生输入：${frame.input}` : '教学提示';
      row.append(el('span', 'frame-input', `第 ${frame.index} 轮 · ${input}`));
      const output = el('div', 'frame-output', frame.output || '此状态没有保存文本。');
      row.append(output);
      if (frame.index === 3 && data.hint_incomplete) {
        row.append(el('p', 'hint-warning', '这条提示记录有不完整输出。页面保留保存文本，不补写模型没有给出的提示内容。'));
      }
      if (frame.action === 'advance' && frame.current_step && frame.total_steps) {
        row.append(el('span', 'frame-input', `该轮实际状态：推进到第 ${frame.current_step} / ${frame.total_steps} 步。`));
      }
      list.append(row);
      math(row);
    }
    full.append(list);
    root.append(full);
  }

  function generation(root, data) {
    root.replaceChildren();
    if (!data.question) {
      root.append(el('p', '', '当前没有保存可展示的变式候选。'));
      return;
    }
    const question = el('div', 'variant-question', data.question);
    root.append(question);
    math(question);
    const verdict = data.accepted
      ? `保存的候选通过三阶段解题检查。该记录包含 ${data.candidate_count} 个候选。`
      : '保存记录中没有候选通过检查。';
    root.append(el('p', 'variant-check', verdict));
    root.append(el('p', 'quality-note', '生成请求基于参考题与步骤结构，没有使用上方的学生错因。因此不能把它描述为由该次诊断自动生成的个性化补练。'));
    const detail = el('details', '');
    detail.append(el('summary', '', '查看保存的变式解题过程'));
    const list = el('ol', 'frame-list');
    for (const step of data.steps || []) {
      const item = el('li', '');
      item.append(el('span', 'frame-input', step.title || '解题过程'));
      item.append(el('div', 'frame-output', step.writing || ''));
      list.append(item);
      math(item);
    }
    detail.append(list);
    root.append(detail);
  }

  async function start() {
    const response = await fetch('/math-case.json', { credentials: 'omit', cache: 'no-store' });
    if (!response.ok) throw new Error(`记录加载失败（HTTP ${response.status}）`);
    const payload = await response.json();
    if (payload.schema_version !== 1 || !payload.case) throw new Error('案例数据格式无法识别');
    const data = payload.case;
    $('#question-text').textContent = data.question || '题目尚未载入。';
    $('#student-answer').textContent = data.student_answer || '作答尚未载入。';
    math($('#question-text'));
    diagnosis($('#diagnosis-result'), data.diagnosis || {});
    comparisons($('#comparison-results'), data.comparisons || []);
    teaching($('#teaching-record'), data.teaching || {});
    generation($('#variant-record'), data.generation || {});
  }

  start().catch(error => {
    for (const id of ['diagnosis-result', 'teaching-record', 'variant-record']) {
      const target = document.getElementById(id);
      target.replaceChildren(el('p', 'quality-note', '保存的案例资料暂时无法载入。请使用专题页查看项目设计和进展。'));
    }
    const status = el('p', 'noscript', error.message);
    document.body.append(status);
  });
})();
