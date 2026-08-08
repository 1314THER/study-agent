/*
 * 五维难度雷达图
 * 兼容新/旧两套维度字段，优先使用数据库或 answer_json 中的五维数据。
 */
(function () {
    var DIM_ORDER = ["非常规程度", "计算量", "分类讨论", "知识广度", "条件转化难度"];
    var LEGACY_MAP = {
        "常规程度": "非常规程度",
        "理解难度": "条件转化难度",
        "涉及到的知识点数量": "知识广度",
        "知识点数量": "知识广度",
        "知识点密度": "知识广度"
    };

    function normalizeDifficultyDims(dims) {
        if (!dims || typeof dims !== "object" || Array.isArray(dims)) return null;
        var out = {};
        var hasAny = false;
        for (var i = 0; i < DIM_ORDER.length; i++) {
            var key = DIM_ORDER[i];
            var raw = dims[key];
            if (raw === undefined && LEGACY_MAP) {
                for (var legacy in LEGACY_MAP) {
                    if (LEGACY_MAP[legacy] === key && dims[legacy] !== undefined) {
                        raw = dims[legacy];
                        break;
                    }
                }
            }
            var num = Number(raw);
            if (isNaN(num)) num = 0;
            num = Math.max(0, Math.min(3, num));
            out[key] = num;
            if (num > 0) hasAny = true;
        }
        return hasAny ? out : (dims && Object.keys(dims).length ? out : null);
    }

    function getDifficultyDims(data) {
        if (!data || typeof data !== "object") return null;
        var candidates = [];
        if (data.overall_difficulty && data.overall_difficulty.dimensions) {
            candidates.push(data.overall_difficulty.dimensions);
        }
        if (data.difficulty && data.difficulty.dimensions) {
            candidates.push(data.difficulty.dimensions);
        }
        if (data.difficulty_dimensions) {
            candidates.push(data.difficulty_dimensions);
        }
        for (var i = 0; i < candidates.length; i++) {
            var raw = candidates[i];
            if (typeof raw === "string") {
                try { raw = JSON.parse(raw); } catch (e) { continue; }
            }
            var normalized = normalizeDifficultyDims(raw);
            if (normalized) return normalized;
        }
        return null;
    }

    function renderDifficultyRadar(container, dims) {
        if (!container) return;
        container.innerHTML = "";
        var data = normalizeDifficultyDims(dims);
        if (!data) {
            var empty = document.createElement("div");
            empty.className = "radar-empty";
            empty.textContent = "暂无五维难度数据";
            container.appendChild(empty);
            return;
        }

        var dpr = window.devicePixelRatio || 1;
        var canvas = document.createElement("canvas");
        var cssW = 400, cssH = 360;
        canvas.width = cssW * dpr;
        canvas.height = cssH * dpr;
        canvas.style.width = cssW + "px";
        canvas.style.height = cssH + "px";
        canvas.style.maxWidth = "100%";
        container.appendChild(canvas);

        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var cx = 200, cy = 185, radius = 100;
        var labels = DIM_ORDER;
        var values = labels.map(function (k) { return data[k]; });
        var n = labels.length;

        var gridColors = ["#f0f0f0", "#e5e5e7", "#d8d8dc"];
        for (var ri = 1; ri <= 3; ri++) {
            var r = radius * ri / 3;
            ctx.beginPath();
            for (var i = 0; i <= n; i++) {
                var angle = (i % n) * 2 * Math.PI / n - Math.PI / 2;
                var x = cx + r * Math.cos(angle);
                var y = cy + r * Math.sin(angle);
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
            ctx.closePath();
            ctx.strokeStyle = gridColors[ri - 1];
            ctx.lineWidth = 1;
            ctx.stroke();
        }

        for (var i = 0; i < n; i++) {
            var angle = i * 2 * Math.PI / n - Math.PI / 2;
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(cx + radius * Math.cos(angle), cy + radius * Math.sin(angle));
            ctx.strokeStyle = "#ececee";
            ctx.lineWidth = 1;
            ctx.stroke();

            var label = labels[i] + " " + values[i];
            ctx.font = "13px -apple-system, sans-serif";
            ctx.fillStyle = "#1d1d1f";
            var lr = radius + 16;
            var nx = cx + lr * Math.cos(angle);
            var ny = cy + lr * Math.sin(angle);
            var deg = ((i / n) * 360) % 360;
            if (deg < 18 || deg >= 342) {
                ctx.textAlign = "center"; ctx.textBaseline = "bottom";
            } else if (deg >= 18 && deg < 72) {
                ctx.textAlign = "left"; ctx.textBaseline = "middle";
            } else if (deg >= 72 && deg < 108) {
                ctx.textAlign = "left"; ctx.textBaseline = "middle";
            } else if (deg >= 108 && deg < 162) {
                ctx.textAlign = "center"; ctx.textBaseline = "top";
            } else if (deg >= 162 && deg < 198) {
                ctx.textAlign = "center"; ctx.textBaseline = "top";
            } else if (deg >= 198 && deg < 252) {
                ctx.textAlign = "right"; ctx.textBaseline = "middle";
            } else if (deg >= 252 && deg < 288) {
                ctx.textAlign = "right"; ctx.textBaseline = "middle";
            } else {
                ctx.textAlign = "right"; ctx.textBaseline = "middle";
            }
            ctx.fillText(label, nx, ny);
        }

        ctx.beginPath();
        for (var i = 0; i <= n; i++) {
            var angle = (i % n) * 2 * Math.PI / n - Math.PI / 2;
            var val = Math.min(values[i % n] / 3, 1);
            var x = cx + radius * val * Math.cos(angle);
            var y = cy + radius * val * Math.sin(angle);
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.closePath();
        var grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
        grad.addColorStop(0, "rgba(0, 113, 227, 0.25)");
        grad.addColorStop(1, "rgba(0, 113, 227, 0.06)");
        ctx.fillStyle = grad;
        ctx.fill();
        ctx.strokeStyle = "#0071e3";
        ctx.lineWidth = 2;
        ctx.stroke();

        for (var i = 0; i < n; i++) {
            var angle = i * 2 * Math.PI / n - Math.PI / 2;
            var val = Math.min(values[i] / 3, 1);
            var x = cx + radius * val * Math.cos(angle);
            var y = cy + radius * val * Math.sin(angle);
            ctx.beginPath();
            ctx.arc(x, y, 4.5, 0, 2 * Math.PI);
            ctx.fillStyle = "#0071e3";
            ctx.fill();
            ctx.beginPath();
            ctx.arc(x, y, 2, 0, 2 * Math.PI);
            ctx.fillStyle = "#fff";
            ctx.fill();
        }

        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        ctx.font = "13px -apple-system, sans-serif";
        ctx.fillStyle = "#86868b";
        ctx.fillText("五维难度分布", cx, cssH - 10);
    }

    window.normalizeDifficultyDims = normalizeDifficultyDims;
    window.getDifficultyDims = getDifficultyDims;
    window.renderDifficultyRadar = renderDifficultyRadar;
})();
