/* Original sources remain visible after a question is promoted to a mother. */
(function () {
  'use strict';
  function escape(value) {
    return String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function sourceHtml(answer) {
    var sources = answer && answer.provenance;
    if (!Array.isArray(sources) || !sources.length) return '';
    var html = '<details class="chunk-card" style="margin-top:16px"><summary style="cursor:pointer;padding:14px">原题出处与参考解析</summary><div style="padding:0 14px 14px;line-height:1.8;white-space:pre-wrap">';
    sources.forEach(function (source) {
      var label = source.source_name || '原题来源';
      var url = null;
      try { var parsed = new URL(String(source.url || '')); if (/^https?:$/.test(parsed.protocol)) url = parsed.href; } catch (_) {}
      html += '<p>' + (url ? '<a href="' + escape(url) + '" target="_blank" rel="noopener noreferrer">' + escape(label) + '</a>' : escape(label));
      if (source.question_no) html += ' · 第 ' + escape(source.question_no) + ' 题';
      if (source.page_start) html += ' · 第 ' + escape(source.page_start) + (source.page_end && source.page_end !== source.page_start ? '–' + escape(source.page_end) : '') + ' 页';
      if (source.source_key) html += '<br><small>' + escape(source.source_key) + '</small>';
      if (source.license) html += '<br><small>' + escape(source.license) + '</small>';
      html += '</p>';
    });
    if (answer.source_answer) html += '<p>原答案：' + escape(answer.source_answer) + '</p>';
    if (answer.source_solution) html += '<p>原解析：</p><div>' + escape(answer.source_solution) + '</div>';
    return html + '</div></details>';
  }
  window.QuestionProvenance = {html: sourceHtml};
})();
