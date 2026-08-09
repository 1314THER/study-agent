(function () {
    if (window.PlannerGlobal) return;
    window.PlannerGlobal = true;

    var API_BASE = 'http://127.0.0.1:8000';
    var TEMPLATES = [
        { key: 'daily1', name: '每天 1 个', desc: '稳妥推进' },
        { key: 'daily2', name: '每天 2 个', desc: '加速复习' },
        { key: 'daily3', name: '每天 3 个', desc: '考前冲刺' }
    ];
    var lastPayload = null;
    var lastPlan = null;

    function injectCss() {
        if (document.getElementById('plannerCss')) return;
        var style = document.createElement('style');
        style.id = 'plannerCss';
        style.textContent = [
            '.planner-launch { padding: 8px 14px; border: 1px solid #16a34a; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; background: #f0fdf4; color: #16a34a; }',
            '.planner-launch:hover { background: #dcfce7; }',
            '.planner-overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.4); z-index: 2000; display: none; align-items: flex-start; justify-content: center; padding: 40px 16px; overflow-y: auto; }',
            '.planner-overlay.show { display: flex; }',
            '.planner-dialog { width: min(680px, 100%); background: #fff; border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,0.2); overflow: hidden; }',
            '.planner-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid #e5e5e7; font-size: 15px; font-weight: 700; }',
            '.planner-close { border: none; background: transparent; font-size: 22px; line-height: 1; cursor: pointer; color: #86868b; }',
            '.planner-body { padding: 16px 18px 20px; }',
            '.planner-section { margin-bottom: 14px; }',
            '.planner-label { font-size: 13px; font-weight: 600; color: #515154; margin-bottom: 8px; }',
            '.planner-templates { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }',
            '.planner-template { border: 1px solid #e3e3e8; border-radius: 10px; padding: 10px 12px; cursor: pointer; background: #fff; text-align: left; transition: all 0.15s; }',
            '.planner-template.active { border-color: #16a34a; background: #f0fdf4; box-shadow: 0 0 0 1px #16a34a; }',
            '.planner-template-name { font-size: 14px; font-weight: 600; color: #1d1d1f; }',
            '.planner-template-desc { font-size: 11px; color: #86868b; margin-top: 2px; }',
            '.planner-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px; }',
            '.planner-field label { display: block; font-size: 12px; color: #515154; margin-bottom: 5px; font-weight: 600; }',
            '.planner-field input { width: 100%; box-sizing: border-box; padding: 8px 10px; border: 1px solid #c7c7cc; border-radius: 8px; font-size: 14px; }',
            '.planner-cats { display: flex; flex-wrap: wrap; gap: 6px; }',
            '.planner-cat { display: inline-flex; align-items: center; gap: 5px; padding: 5px 9px; border: 1px solid #e3e3e8; border-radius: 999px; font-size: 12px; cursor: pointer; background: #fff; }',
            '.planner-cat.checked { background: #f0fdf4; border-color: #86efac; color: #166534; }',
            '.planner-actions { display: flex; gap: 10px; margin-top: 4px; }',
            '.planner-btn { padding: 9px 16px; border: none; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; }',
            '.planner-btn.primary { background: #16a34a; color: #fff; }',
            '.planner-btn.secondary { background: #f5f5f7; color: #515154; }',
            '.planner-btn:disabled { opacity: 0.5; cursor: default; }',
            '.planner-preview { margin-top: 14px; }',
            '.planner-summary { font-size: 13px; color: #166534; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 8px 12px; margin-bottom: 10px; }',
            '.planner-day { border: 1px solid #e5e5e7; border-radius: 10px; padding: 9px 12px; margin-bottom: 8px; background: #fafafa; }',
            '.planner-day-title { font-size: 13px; font-weight: 700; color: #1d1d1f; margin-bottom: 6px; }',
            '.planner-day-items { display: flex; flex-wrap: wrap; gap: 6px; }',
            '.planner-item { font-size: 12px; padding: 4px 10px; border-radius: 999px; background: #fff; border: 1px solid #e3e3e8; color: #1d1d1f; }',
            '.planner-item .cat { color: #86868b; margin-left: 4px; }',
            '.planner-status { margin-top: 10px; font-size: 13px; color: #166534; min-height: 18px; }',
            '.planner-status.error { color: #c62828; }',
            '@media (max-width: 640px) { .planner-templates { grid-template-columns: 1fr; } .planner-row { grid-template-columns: 1fr; } }'
        ].join('\n');
        document.head.appendChild(style);
    }

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function fmtDate(d) {
        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }

    function defaultStart() {
        var d = new Date();
        d.setDate(d.getDate() + 1);
        return fmtDate(d);
    }

    function buildModal() {
        var overlay = document.createElement('div');
        overlay.className = 'planner-overlay';
        overlay.id = 'plannerOverlay';
        overlay.innerHTML =
            '<div class="planner-dialog">' +
            '<div class="planner-head"><span>一键规划</span><button class="planner-close" type="button" aria-label="关闭">×</button></div>' +
            '<div class="planner-body">' +
            '<div class="planner-section"><div class="planner-label">学习节奏</div><div class="planner-templates" id="plannerTemplates"></div></div>' +
            '<div class="planner-row">' +
            '<div class="planner-field"><label for="plannerStart">开始日期</label><input type="date" id="plannerStart"></div>' +
            '<div class="planner-field"><label for="plannerPerDay">每天数量</label><input type="number" id="plannerPerDay" min="1" max="10" value="1"></div>' +
            '</div>' +
            '<div class="planner-section"><div class="planner-label">只规划这些板块（不选就是全部未掌握）</div><div class="planner-cats" id="plannerCats"></div></div>' +
            '<div class="planner-actions">' +
            '<button class="planner-btn secondary" id="plannerPreview" type="button">生成预览</button>' +
            '<button class="planner-btn primary" id="plannerApply" type="button" disabled>确认写入日历</button>' +
            '</div>' +
            '<div class="planner-preview" id="plannerPreviewBox"></div>' +
            '<div class="planner-status" id="plannerStatus"></div>' +
            '</div>' +
            '</div>';
        document.body.appendChild(overlay);

        overlay.querySelector('.planner-close').addEventListener('click', function () {
            overlay.classList.remove('show');
        });
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) overlay.classList.remove('show');
        });

        var templatesEl = document.getElementById('plannerTemplates');
        TEMPLATES.forEach(function (t) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'planner-template';
            btn.dataset.template = t.key;
            btn.innerHTML = '<div class="planner-template-name">' + escapeHtml(t.name) + '</div><div class="planner-template-desc">' + escapeHtml(t.desc) + '</div>';
            btn.addEventListener('click', function () {
                setTemplate(t.key);
            });
            templatesEl.appendChild(btn);
        });
        setTemplate('daily1');

        document.getElementById('plannerStart').value = defaultStart();
        document.getElementById('plannerPreview').addEventListener('click', previewPlan);
        document.getElementById('plannerApply').addEventListener('click', applyPlan);
    }

    function setTemplate(key) {
        var buttons = document.querySelectorAll('.planner-template');
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].classList.toggle('active', buttons[i].dataset.template === key);
        }
        document.getElementById('plannerPerDay').value = ({ daily1: 1, daily2: 2, daily3: 3 })[key] || 1;
        lastPayload = null;
        lastPlan = null;
        document.getElementById('plannerApply').disabled = true;
        document.getElementById('plannerPreviewBox').innerHTML = '';
        document.getElementById('plannerStatus').textContent = '';
    }

    function loadCategories() {
        var catsEl = document.getElementById('plannerCats');
        fetch(API_BASE + '/planner/board-order')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var order = data.board_order || [];
                order.forEach(function (item) {
                    var label = document.createElement('label');
                    label.className = 'planner-cat checked';
                    var cb = document.createElement('input');
                    cb.type = 'checkbox';
                    cb.checked = true;
                    cb.style.display = 'none';
                    cb.value = item.category;
                    label.appendChild(cb);
                    label.appendChild(document.createTextNode(item.category));
                    label.addEventListener('click', function () {
                        cb.checked = !cb.checked;
                        label.classList.toggle('checked', cb.checked);
                    });
                    catsEl.appendChild(label);
                });
            })
            .catch(function () {
                catsEl.innerHTML = '<span style="font-size:12px;color:#86868b;">板块顺序配置加载失败</span>';
            });
    }

    function collectPayload() {
        var activeTemplate = null;
        var buttons = document.querySelectorAll('.planner-template.active');
        if (buttons.length) activeTemplate = buttons[0].dataset.template;
        var perDay = parseInt(document.getElementById('plannerPerDay').value, 10);
        if (!perDay || perDay < 1) perDay = 1;
        if (perDay > 10) perDay = 10;
        var cats = [];
        var labels = document.querySelectorAll('#plannerCats .planner-cat');
        for (var i = 0; i < labels.length; i++) {
            var cb = labels[i].querySelector('input');
            if (cb && cb.checked) cats.push(cb.value);
        }
        return {
            template: activeTemplate,
            per_day: perDay,
            start_date: document.getElementById('plannerStart').value || defaultStart(),
            categories: cats
        };
    }

    function previewPlan() {
        var payload = collectPayload();
        var statusEl = document.getElementById('plannerStatus');
        var box = document.getElementById('plannerPreviewBox');
        statusEl.textContent = '正在生成预览…';
        statusEl.classList.remove('error');
        fetch(API_BASE + '/planner/plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                lastPayload = payload;
                lastPlan = data;
                document.getElementById('plannerApply').disabled = false;
                statusEl.textContent = '';
                renderPreview(data);
            })
            .catch(function () {
                statusEl.textContent = '生成预览失败，请确认后端已启动。';
                statusEl.classList.add('error');
            });
    }

    function renderPreview(data) {
        var box = document.getElementById('plannerPreviewBox');
        if (!data || !data.plan) {
            box.innerHTML = '<div class="planner-summary">没有可规划的未掌握套路。</div>';
            return;
        }
        var html = '<div class="planner-summary">共 ' + data.total_patterns + ' 个套路，每天 ' + data.per_day +
            ' 个，从 ' + data.start_date + ' 开始，共 ' + data.days + ' 天。</div>';
        data.plan.forEach(function (day) {
            html += '<div class="planner-day"><div class="planner-day-title">' + escapeHtml(day.date) + '</div><div class="planner-day-items">';
            day.patterns.forEach(function (p) {
                html += '<span class="planner-item">' + escapeHtml(p.name) + '<span class="cat">' + escapeHtml(p.category) + '</span></span>';
            });
            html += '</div></div>';
        });
        box.innerHTML = html;
    }

    function applyPlan() {
        if (!lastPayload) return;
        var statusEl = document.getElementById('plannerStatus');
        var applyBtn = document.getElementById('plannerApply');
        applyBtn.disabled = true;
        statusEl.textContent = '正在写入日历…';
        statusEl.classList.remove('error');
        fetch(API_BASE + '/planner/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(lastPayload)
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.applied != null) {
                    statusEl.textContent = '已写入 ' + data.applied + ' 个套路到巩固日历，正在刷新…';
                    setTimeout(function () { location.reload(); }, 900);
                } else {
                    statusEl.textContent = '写入失败：' + (data.error || '未知错误');
                    statusEl.classList.add('error');
                    applyBtn.disabled = false;
                }
            })
            .catch(function () {
                statusEl.textContent = '写入失败，请确认后端已启动。';
                statusEl.classList.add('error');
                applyBtn.disabled = false;
            });
    }

    function init() {
        injectCss();
        buildModal();
        loadCategories();
        var header = document.querySelector('.cal-top') || document.querySelector('.loop-header');
        if (!header) return;
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'planner-launch';
        btn.textContent = '一键规划';
        btn.addEventListener('click', function () {
            document.getElementById('plannerOverlay').classList.add('show');
        });
        header.appendChild(btn);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
