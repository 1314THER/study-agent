/* Display adapters for imported TeX. Archived source text is never rewritten. */
(function (root) {
  'use strict';
  var MACROS = {'\\e': '\\mathrm{e}', '\\i': '\\mathrm{i}', '\\bs': '\\boldsymbol{#1}', '\\myarc': '\\overset{\\frown}{#1}', '\\overparen': '\\overgroup{#1}', '\\oversetfrown': '\\overset{\\frown}{#1}', '\\Perp': '\\perp', '\\Square': '\\square', '\\textasciitilde': '\\sim'};
  // Standard KaTeX commands that share a prefix with the source's concatenated
  // operator-plus-variable forms must remain a single command.
  var STANDARD_COMMANDS = new Set(['\\cdots','\\cdotp','\\includegraphics','\\inf','\\infin','\\infty','\\injlim','\\int','\\intop','\\intercal','\\pmb','\\pmod','\\sinh','\\cosh','\\tanh','\\triangledown','\\triangleleft','\\trianglelefteq','\\triangleq','\\triangleright','\\trianglerighteq']);
  var ENVIRONMENTS = /^(?:align\*?|aligned|alignedat|equation\*?|gather\*?|gathered|cases|dcases|array|[pbBvV]?matrix|smallmatrix|split)$/;
  function argument(text, start) {
    while (/\s/.test(text[start] || '') && start < text.length) start++;
    if (text[start] !== '{') return null;
    var depth = 1, pos = start + 1;
    for (; pos < text.length; pos++) {
      if (text[pos] === '\\') { pos++; continue; }
      if (text[pos] === '{') depth++;
      if (text[pos] === '}' && --depth === 0) return {value: text.slice(start + 1, pos), end: pos + 1};
    }
    return null;
  }
  function commands(text, expression, count, replacement) {
    var out = '', cursor = 0, match;
    expression.lastIndex = 0;
    while ((match = expression.exec(text))) {
      var pos = expression.lastIndex, values = [], value;
      for (var i = 0; i < count; i++) { value = argument(text, pos); if (!value) break; values.push(value.value); pos = value.end; }
      if (values.length !== count) continue;
      out += text.slice(cursor, match.index) + replacement(values, match); cursor = pos; expression.lastIndex = pos;
    }
    return out + text.slice(cursor);
  }
  function presentation(text) {
    // Older imports confused the row spacing \\[4pt] with the display opener \[.
    text = String(text || '').replace(/\\\$\$([+-]?(?:\d*\.)?\d+(?:pt|ex|em|mm|cm|bp))\]/g, '\\\\[$1]');
    text = commands(text, /\\examdisplaycases\b/g, 2, function (v) { return '\\[' + v[0] + '\\begin{cases}' + v[1] + '\\end{cases}\\]'; });
    text = commands(text, /\\examdisplayarray\b/g, 4, function (v) { return '\\[' + v[0] + '\\begin{array}{' + v[1] + '}' + v[2] + '\\end{array}' + v[3] + '\\]'; });
    text = commands(text, /\\examdisplay(?:chain|aligned)\b(?:\[[^\]]*\])?/g, 1, function (v) { return '\\[\\begin{aligned}' + v[0] + '\\end{aligned}\\]'; });
    text = commands(text, /\\choices\b(?:\[[^\]]*\])?/g, 4, function (v) { return '\n' + v.map(function (s, i) { return 'ABCD'[i] + '. ' + s; }).join('\n\n'); });
    text = commands(text, /\\choicesfive\b(?:\[[^\]]*\])?/g, 5, function (v) { return '\n' + v.map(function (s, i) { return 'ABCDE'[i] + '. ' + s; }).join('\n\n'); });
    text = commands(text, /\\(?:choicebitmap|choicetexfigure|bitmapfigure|texfigure)\b(?:\[[^\]]*\])?/g, 1, function () { return '[原题含图，本阶段暂缓]'; });
    text = commands(text, /\\bitmapinclude\b(?:\[[^\]]*\])?/g, 1, function () { return '[原题含图，本阶段暂缓]'; });
    text = commands(text, /\\solutionfigure\b/g, 1, function () { return '[原题含图，本阶段暂缓]'; });
    text = commands(text, /\\FigureTrimDeclare\b/g, 2, function () { return '[原题含图，本阶段暂缓]'; });
    return text;
  }
  function mathSource(value) {
    // A TeX blank is a rule, not a chain of subscripts. Font commands used as
    // single fraction arguments need a group in KaTeX after source conversion.
    return value.replace(/\\(Leftrightarrow|Longrightarrow|Rightarrow|rightarrow|leftarrow|leftrightarrow|therefore|because|cdot|times|neq|leqslant|geqslant|approx|equiv|pm|angle|triangle|Delta|alpha|beta|gamma|theta|lambda|rho|odot|oplus|otimes|cup|cap|cos|sin|tan|sinh|cosh|tanh|log|ln|pi|bot|in)([A-Za-z]+)(?![A-Za-z])/g, function (full, command, suffix) {
      return STANDARD_COMMANDS.has('\\' + command + suffix) ? full : '\\' + command + ' ' + suffix;
    })
      .replace(/\\(sin|cos|tan)([A-Z])(?![A-Za-z])/g, '\\$1 $2')
      .replace(/(?<!\\)_{2,}/g, '\\underline{\\qquad}')
      .replace(/\\(?:mathrm|mathbb|boldsymbol)\s*\{[^{}]*\}/g, '{$&}')
      .replace(/\\[,;!:](?=\s*[_^])/g, '$&{}');
  }
  function mathLayout(value) {
    value = commands(value, /\\parbox\b(?:\[[^\]]*\]){0,3}/g, 2, function (v) { return v[1]; });
    value = commands(value, /\\resizebox\b/g, 3, function (v) { return v[2]; });
    value = commands(value, /\\rotatebox\b(?:\[[^\]]*\])?/g, 2, function (v) { return v[1]; });
    value = commands(value, /\\raisebox\b(?:\[[^\]]*\])?/g, 2, function (v) { return v[1]; });
    value = commands(value, /\\(?:smash|rlap)\b/g, 1, function (v) { return v[0]; });
    value = commands(value, /\\rule\b(?:\[[^\]]*\])?/g, 2, function () { return ''; });
    value = commands(value, /\\makebox\b(?:\[[^\]]*\]){0,2}/g, 1, function (v) {
      return /[\u3400-\u9fff]/.test(v[0]) ? '\\text{' + v[0] + '}' : v[0];
    });
    value = commands(value, /\\(?:section\*?|subsection\*?)(?![A-Za-z])/g, 1, function (v) { return /[\u3400-\u9fff]/.test(v[0]) ? '\\text{' + v[0] + '}' : v[0]; });
    return value;
  }
  function nestedDollars(value) {
    var depth = 0, out = '';
    for (var pos = 0; pos < value.length; pos++) {
      var ch = value[pos];
      if (ch === '\\') { out += ch + (value[++pos] || ''); continue; }
      if (ch === '{') depth++;
      if (ch === '}') depth--;
      if (ch !== '$' || depth > 0) out += ch;
    }
    return out;
  }
  function cleanText(text) {
    text = commands(text, /\\FigureLayoutDeclare\b/g, 3, function () { return ''; });
    text = commands(text, /\\(?:setlength|setcounter|renewcommand)\b/g, 2, function () { return ''; });
    text = commands(text, /\\(?:vspace\*?|everypar)\b/g, 1, function () { return ''; });
    text = commands(text, /\\examfiguregroup\b(?:\[[^\]]*\])?/g, 2, function () { return '[原题含图，本阶段暂缓]'; });
    text = commands(text, /\\resizebox\b/g, 3, function (v) { return v[2]; });
    text = commands(text, /\\parbox\b(?:\[[^\]]*\]){0,3}/g, 2, function (v) { return v[1]; });
    text = commands(text, /\\(?:makebox|mbox)\b(?:\[[^\]]*\]){0,2}/g, 1, function (v) { return v[0]; });
    text = commands(text, /\\(?:text(?:bf|it|normal)?|section\*?)(?![A-Za-z])/g, 1, function (v) { return v[0]; });
    text = commands(text, /\\begin\{minipage\}(?:\[[^\]]*\])?/g, 1, function () { return ''; });
    return text.replace(/\\(?:begin|end)\{(?:center|flushleft|flushright)\}/g, '\n')
      .replace(/\\end\{minipage\}/g, '')
      .replace(/\\(?:leftskip|rightskip|hbadness)\s*=\s*[\d.]+(?:pt|em|ex)?\s*(?:\\relax)?/g, '')
      .replace(/\\(?:begingroup|endgroup|centering|FloatBarrier|tallpagetrue|hfill|par|scriptsize|footnotesize|smallskip|medskip|bigskip|noindent|problemresetlayout)\b/g, '')
      .replace(/\\(?:quad|qquad)\b/g, '　').replace(/\n{3,}/g, '\n\n');
  }
  function endMath(text, pos, right) {
    var depth = 0, environments = 0;
    for (; pos < text.length; pos++) {
      var env = /^\\(begin|end)\{([^}]+)\}/.exec(text.slice(pos));
      if (env) { environments += env[1] === 'begin' ? 1 : -1; pos += env[0].length - 1; continue; }
      if (depth <= 0 && environments <= 0 && text.startsWith(right, pos)) return pos;
      if (text[pos] === '\\') { pos++; continue; }
      if (text[pos] === '{') depth++;
      if (text[pos] === '}') depth--;
    }
    return -1;
  }
  function endEnvironment(text, start, name) {
    var pattern = /\\(begin|end)\{([^}]+)\}/g, depth = 1, match; pattern.lastIndex = start;
    while ((match = pattern.exec(text))) if (match[2] === name) { depth += match[1] === 'begin' ? 1 : -1; if (!depth) return match.index; }
    return -1;
  }
  function splitCells(text, rows) {
    var values = [], cursor = 0, braces = 0, environments = 0;
    for (var pos = 0; pos < text.length; pos++) {
      var env = /^\\(begin|end)\{[^}]+\}/.exec(text.slice(pos));
      if (env) { environments += env[1] === 'begin' ? 1 : -1; pos += env[0].length - 1; continue; }
      var divider = rows ? text.startsWith('\\\\', pos) : text[pos] === '&';
      if (divider && braces === 0 && environments === 0) {
        values.push(text.slice(cursor, pos)); pos += rows ? 1 : 0;
        if (rows) { var gap = /^\[[^\]]*\]/.exec(text.slice(pos + 1)); if (gap) pos += gap[0].length; }
        cursor = pos + 1; continue;
      }
      if (text[pos] === '\\') { pos++; continue; }
      if (text[pos] === '{') braces++;
      if (text[pos] === '}') braces--;
    }
    values.push(text.slice(cursor)); return values;
  }
  function table(text) {
    var start = /^\\begin\{tabular\}(?:\[[^\]]*\])?/.exec(text), spec = start && argument(text, start[0].length);
    if (!spec || !text.endsWith('\\end{tabular}')) return null;
    var body = text.slice(spec.end, -'\\end{tabular}'.length).replace(/\\(?:hline|toprule|midrule|bottomrule)\b|\\cline\s*\{[^}]+\}/g, '');
    var rows = splitCells(body, true).map(function (row) { return row.trim(); }).filter(Boolean).map(function (row) {
      return splitCells(row, false).map(function (cell) {
        cell = cell.trim(); var span = 1, rowSpan = 1;
        cell = commands(cell, /\\multicolumn\b/g, 3, function (v) { span = Math.max(1, Math.min(50, Number(v[0]) || 1)); return v[2]; });
        cell = commands(cell, /\\multirow\b/g, 3, function (v) { rowSpan = Math.max(1, Math.min(50, Number(v[0]) || 1)); return v[2]; });
        return {text: cell, span: span, rowSpan: rowSpan};
      });
    });
    return {type: 'table', rows: rows};
  }
  function unmarkedParts(text) {
    // Some datasets omit math delimiters. Split at prose boundaries outside
    // braced TeX arguments, preserving every symbol. Unknown macros stay visible.
    var values = [], cursor = 0, braces = 0;
    function chunk(value) {
      if (!value) return;
      var hasMath = /\\[A-Za-z]+|[A-Za-z0-9)][_^](?:\{|\d|[A-Za-z])/.test(value) && !/\$|https?:\/\//.test(value);
      values.push(hasMath ? {type:'math', text:mathSource(mathLayout(value)), raw:value, display:false} : {type:'text', text:value});
    }
    for (var pos = 0; pos < text.length; pos++) {
      if (text[pos] === '\\') { var token = /^\\(?:[A-Za-z]+|.)/.exec(text.slice(pos)); if (token) { pos += token[0].length - 1; continue; } }
      if (text[pos] === '{') braces++;
      if (text[pos] === '}') braces--;
      if (braces === 0 && /[\u3400-\u9fff，。；：！？\n]/.test(text[pos])) { chunk(text.slice(cursor, pos)); values.push({type:'text', text:text[pos]}); cursor = pos + 1; }
    }
    chunk(text.slice(cursor)); return values;
  }
  function parts(input) {
    var text = presentation(input), result = [], cursor = 0, pattern = /\$\$|\$|\\\[|\\\(|\\begin\{([^}]+)\}/g, match;
    function plain(value) { if (value) result.push.apply(result, unmarkedParts(cleanText(value))); }
    while ((match = pattern.exec(text))) {
      // Escaped currency and the second slash of a row break are not delimiters.
      var escapes = 0; for (var p = match.index - 1; p >= 0 && text[p] === '\\'; p--) escapes++;
      if (escapes % 2) continue;
      var left = match[0], env = match[1];
      if (env && !ENVIRONMENTS.test(env) && env !== 'tabular') continue;
      var right = env ? '\\end{' + env + '}' : left === '\\[' ? '\\]' : left === '\\(' ? '\\)' : left;
      var end = env ? endEnvironment(text, pattern.lastIndex, env) : endMath(text, pattern.lastIndex, right);
      plain(text.slice(cursor, match.index));
      if (end < 0) { result.push({type:'text', text:text.slice(match.index), warning:'公式分隔符或括号未闭合，保留原文待核对'}); cursor = text.length; break; }
      var raw = text.slice(match.index, end + right.length), value = env ? raw : text.slice(pattern.lastIndex, end);
      var t = table(value.trim());
      if (t) result.push(t);
      else {
        if (/\\begin\{/.test(value)) value = nestedDollars(value);
        else if (left === '\\(' && /^\s*\$[^]*\$\s*$/.test(value)) value = value.trim().slice(1, -1);
        result.push({type:'math', text:mathSource(mathLayout(value)), raw:raw, display:!!env || left === '$$' || left === '\\[' || /\\begin\{(?:align\*?|equation\*?|gather\*?|cases|dcases|array)\}/.test(value)});
      }
      cursor = end + right.length; pattern.lastIndex = cursor;
    }
    plain(text.slice(cursor));
    return result;
  }
  function render(target, text, options) {
    options = options || {}; var doc = options.document || target.ownerDocument, katex = options.katex || root.katex, warnings = [], count = 0;
    target.replaceChildren();
    function append(parent, segments) {
      segments.forEach(function (part) {
        if (part.type === 'table') {
          var scroll = doc.createElement('div'), grid = doc.createElement('table'); scroll.className = 'pool-table-scroll'; grid.className = 'pool-source-table';
          part.rows.forEach(function (row) { var tr = doc.createElement('tr'); row.forEach(function (cell) { var td = doc.createElement('td'); td.colSpan = cell.span; td.rowSpan = cell.rowSpan; append(td, parts(cell.text)); tr.appendChild(td); }); grid.appendChild(tr); }); scroll.appendChild(grid); parent.appendChild(scroll); return;
        }
        var node = doc.createElement('span');
        if (part.type === 'math' && katex) {
          try { katex.render(part.text, node, {displayMode:part.display, throwOnError:true, trust:false, strict:'ignore', maxExpand:1000, macros:Object.assign({}, MACROS)}); count++; }
          catch (_) { node.textContent = part.raw; node.className = 'pool-math-unresolved'; warnings.push('公式转录或命令不受支持，保留原文待核对'); }
        } else {
          node.textContent = part.type === 'math' ? part.raw : part.text;
          if (part.warning) warnings.push(part.warning);
          if (part.type === 'math') warnings.push('公式组件未加载，暂时显示原文');
          if (part.type === 'text' && /\\[A-Za-z]+|[_^]\{/.test(part.text)) warnings.push('原文含未标记或未识别的公式，需核对转录');
        }
        parent.appendChild(node);
      });
    }
    append(target, parts(text));
    if (warnings.length) { var note = doc.createElement('small'); note.className = 'pool-math-warning'; note.textContent = Array.from(new Set(warnings)).join('；'); target.appendChild(note); }
    return {formulas:count, warnings:warnings};
  }
  root.PoolMath = {parts:parts, render:render, macros:MACROS, mathSource:mathSource};
  if (typeof module === 'object' && module.exports) module.exports = root.PoolMath;
})(typeof window === 'object' ? window : globalThis);
