/*
 * 五维难度柱状图：把 step_difficulty.dimensions 渲染成五根横向小柱。
 * 挂到 window.renderDimBarsHtml / renderDimBarsFromValues，页面里直接拼进 HTML 字符串。
 */
(function () {
    var DIM_ORDER = ["非常规程度", "计算量", "分类讨论", "知识广度", "条件转化难度"];

    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    function clamp(v) {
        var n = parseInt(v, 10);
        if (isNaN(n)) return 0;
        return Math.max(0, Math.min(3, n));
    }

    function scoreClass(v) {
        if (v >= 3) return "lv3";
        if (v === 2) return "lv2";
        if (v === 1) return "lv1";
        return "lv0";
    }

    function barsHtml(values, compact) {
        if (!values || values.length !== 5) return "";
        var html = '<div class="dim-bars' + (compact ? ' dim-bars-compact' : '') + '">';
        for (var i = 0; i < DIM_ORDER.length; i++) {
            var v = clamp(values[i]);
            var pct = Math.round(v / 3 * 100);
            html += '<div class="dim-bar-row">';
            html += '<span class="dim-bar-label">' + DIM_ORDER[i] + '</span>';
            html += '<span class="dim-bar-track"><span class="dim-bar-fill ' + scoreClass(v) + '" style="width:' + pct + '%"></span></span>';
            html += '<span class="dim-bar-value ' + scoreClass(v) + '">' + v + '</span>';
            html += '</div>';
        }
        html += '</div>';
        return html;
    }

    window.renderDimBarsHtml = function (dims, compact) {
        if (!dims || typeof dims !== "object") return "";
        return barsHtml(DIM_ORDER.map(function (name) { return clamp(dims[name]); }), compact);
    };

    window.renderDimBarsFromValues = function (values, compact) {
        return barsHtml(values, compact);
    };
})();
