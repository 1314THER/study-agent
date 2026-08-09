(function () {
    if (window.AgentGlobal) return;

    var API_BASE = (function () {
        try {
            if (location.protocol === 'http:' || location.protocol === 'https:') return location.origin;
        } catch (e) {}
        return 'http://127.0.0.1:8000';
    })();
    var CART_KEY = 'exam_cart';
    var KATEX_VERSION = '0.16.9';
    var state = { busy: false };
    var lastSearch = [];
    var hostEl = null;
    var messagesEl = null;
    var inputEl = null;
    var sendBtn = null;

    function injectCss() {
        if (document.querySelector('link[data-agent-css]')) return;
        var link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = 'agent.css?v=20260809e';
        link.setAttribute('data-agent-css', '1');
        document.head.appendChild(link);
    }

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function plainText(html) {
        var d = document.createElement('div');
        d.innerHTML = String(html == null ? '' : html);
        return (d.textContent || '').trim();
    }

    function ensureKatex(cb) {
        if (window.renderMathInElement) { cb(); return; }
        if (!ensureKatex.loading) {
            ensureKatex.loading = true;
            ensureKatex.waiters = [];
            var css = document.createElement('link');
            css.rel = 'stylesheet';
            css.href = 'https://cdn.jsdelivr.net/npm/katex@' + KATEX_VERSION + '/dist/katex.min.css';
            document.head.appendChild(css);
            var s = document.createElement('script');
            s.src = 'https://cdn.jsdelivr.net/npm/katex@' + KATEX_VERSION + '/dist/katex.min.js';
            s.onload = function () {
                var ar = document.createElement('script');
                ar.src = 'https://cdn.jsdelivr.net/npm/katex@' + KATEX_VERSION + '/dist/contrib/auto-render.min.js';
                ar.onload = function () {
                    ensureKatex.loading = false;
                    var waiters = ensureKatex.waiters.splice(0);
                    waiters.forEach(function (fn) { fn(); });
                };
                document.head.appendChild(ar);
            };
            document.head.appendChild(s);
        }
        ensureKatex.waiters.push(cb);
    }

    function renderMath(root) {
        if (!window.renderMathInElement) return;
        try {
            window.renderMathInElement(root, {
                delimiters: [
                    { left: '$$', right: '$$', display: true },
                    { left: '$', right: '$', display: false },
                    { left: '\\(', right: '\\)', display: false },
                    { left: '\\[', right: '\\]', display: true }
                ],
                ignoredTags: ['script', 'style']
            });
        } catch (e) {}
    }

    function addMessage(role, text) {
        var box = document.createElement('div');
        box.className = 'agent-msg agent-msg-' + role;
        var bubble = document.createElement('div');
        bubble.className = 'agent-bubble';
        bubble.textContent = text;
        box.appendChild(bubble);
        messagesEl.appendChild(box);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        return box;
    }

    function addActionBlock(title, text) {
        var box = addMessage('agent', text);
        if (title) {
            var titleEl = document.createElement('div');
            titleEl.className = 'agent-action-title';
            titleEl.textContent = title;
            box.appendChild(titleEl);
        }
        var body = document.createElement('div');
        body.className = 'agent-action-body';
        box.appendChild(body);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        return { box: box, body: body };
    }

    function readCart() {
        try {
            var raw = localStorage.getItem(CART_KEY);
            return raw ? JSON.parse(raw) : [];
        } catch (e) { return []; }
    }

    function writeCart(items) {
        try { localStorage.setItem(CART_KEY, JSON.stringify(items)); } catch (e) {}
    }

    function addToCart(items) {
        var cart = readCart();
        var added = 0;
        items.forEach(function (item) {
            var id = Number(item.id);
            if (cart.some(function (x) { return Number(x.id) === id; })) return;
            cart.push({
                id: id,
                preview: String(item.preview || '').slice(0, 30),
                settings: { blankHeight: 120, showDifficulty: false, showDetailedProcess: false, showKnowledgePoints: true }
            });
            added++;
        });
        writeCart(cart);
        addActionBlock('组卷篮子', '已加入 ' + added + ' 道题，当前共 ' + cart.length + ' 道。');
        updateHomeStats({});
    }

    function renderQuestionCards(items, container) {
        lastSearch = items || [];
        items.forEach(function (q) {
            var card = document.createElement('div');
            card.className = 'agent-qcard';
            var meta = [];
            if (q.question_type) meta.push(q.question_type);
            if (q.category_level1) meta.push(q.category_level1);
            if (q.difficulty_level) meta.push(q.difficulty_level);
            if (q.source_type) meta.push(q.source_type);
            var text = String(q.content || '').trim();
            card.innerHTML =
                '<div class="agent-qmeta">' + meta.map(escapeHtml).join(' · ') + '</div>' +
                '<div class="agent-qtext">' + escapeHtml(text) + '</div>' +
                '<div class="agent-qactions">' +
                '<button type="button" data-act="detail" data-qid="' + q.id + '">查看解析</button>' +
                '<button type="button" data-act="teach" data-qid="' + q.id + '">手把手教学</button>' +
                '<button type="button" data-act="cart" data-qid="' + q.id + '">加入组卷</button>' +
                '</div>';
            var buttons = card.querySelectorAll('button[data-act]');
            for (var i = 0; i < buttons.length; i++) {
                (function (btn) {
                    btn.addEventListener('click', function () {
                        var id = Number(btn.getAttribute('data-qid'));
                        var q2 = lastSearch.find(function (x) { return String(x.id) === String(id); }) || {};
                        var act = btn.getAttribute('data-act');
                        if (act === 'detail') {
                            localStorage.setItem('_open_question_id', String(id));
                            location.href = 'history.html';
                        } else if (act === 'teach') {
                            localStorage.setItem('_teach_question', String(q2.content || ''));
                            location.href = 'teach.html?standalone=1';
                        } else {
                            addToCart([{ id: id, preview: plainText(String(q2.content || '')).slice(0, 30) }]);
                        }
                    });
                })(buttons[i]);
            }
            container.appendChild(card);
        });
        ensureKatex(function () { renderMath(container); });
    }

    function navigate(a) {
        var map = {
            home: 'home.html', solve: 'index.html', multimodal: 'multimodal.html',
            teach: 'teach.html', history: 'history.html', exam: 'exam.html',
            grade: 'grade.html', settings: 'settings.html', mother: 'mother.html',
            loop: 'loop.html', calendar: 'calendar.html', board: 'board.html'
        };
        var p = a.params || {};
        var url = map[a.page] || 'home.html';
        if (a.page === 'solve' && p.input) {
            localStorage.setItem('solve_input', String(p.input));
            url = 'index.html?auto=1';
        }
        if (a.page === 'history' && p.qid) {
            localStorage.setItem('_open_question_id', String(p.qid));
            url = 'history.html';
        }
        if (a.page === 'teach' && p.question) {
            localStorage.setItem('_teach_question', String(p.question));
            url = 'teach.html?standalone=1';
        }
        if (a.page === 'grade' && p.qid) {
            url = 'grade.html?question_id=' + encodeURIComponent(String(p.qid));
        }
        location.href = url;
    }

    function openQuestion(id) {
        localStorage.setItem('_open_question_id', String(id));
        location.href = 'history.html';
    }

    function startTeach(question) {
        if (question) {
            localStorage.setItem('_teach_question', String(question));
            location.href = 'teach.html?standalone=1';
        } else {
            location.href = 'teach.html';
        }
    }

    function startSolve(question) {
        if (question) {
            localStorage.setItem('solve_input', String(question));
            location.href = 'index.html?auto=1';
        } else {
            location.href = 'index.html';
        }
    }

    function openGrade(a) {
        var qid = a.params && a.params.question_id;
        location.href = qid ? 'grade.html?question_id=' + encodeURIComponent(String(qid)) : 'grade.html';
    }

    async function runSearch(a) {
        var params = new URLSearchParams();
        var f = a.filters || {};
        if (a.query) params.set('q', a.query);
        if (f.category) params.set('category', f.category);
        if (f.question_type) params.set('question_type', f.question_type);
        if (f.difficulty) params.set('difficulty', f.difficulty);
        if (f.error_type) params.set('error_type', f.error_type);
        if (f.source_type) params.set('source_type', f.source_type);
        var limit = Math.min(Math.max(parseInt(a.limit, 10) || 5, 1), 30);
        params.set('limit', String(limit));
        params.set('mode', 'global');
        var res = await fetch(API_BASE + '/questions/search?' + params.toString());
        var data = await res.json();
        var items = Array.isArray(data) ? data : (data.data || []);
        lastSearch = items;
        var block = addActionBlock(
            '搜到的题目',
            items.length ? '共找到 ' + items.length + ' 道，可直接操作下方卡片。' : '没有找到符合条件的题目。'
        );
        if (items.length) renderQuestionCards(items.slice(0, Math.min(limit, 10)), block.body);
    }

    async function addToCartAction(a) {
        var ids = (a.ids || []).map(Number);
        if (!ids.length && a.source === 'search' && lastSearch.length) {
            ids = lastSearch.slice(0, Math.min(a.limit || 5, lastSearch.length)).map(function (q) { return q.id; });
        }
        var items = ids.map(function (id) {
            var q = lastSearch.find(function (x) { return String(x.id) === String(id); }) || {};
            return { id: id, preview: plainText(String(q.content || '')).slice(0, 30) };
        });
        if (items.length) addToCart(items);
    }

    async function loadContext() {
        var res = await fetch(API_BASE + '/agent/context');
        var ctx = await res.json();
        updateHomeStats(ctx);
        addActionBlock('当前学情', [
            ctx.total_questions != null ? '题库题目：' + ctx.total_questions : '',
            ctx.wrong_questions != null ? '错题标记：' + ctx.wrong_questions : '',
            ctx.due_reviews != null ? '今日待复习：' + ctx.due_reviews : '',
            ctx.patterns_mastered != null ? '掌握套路：' + ctx.patterns_mastered + ' / ' + (ctx.patterns_total || 0) : ''
        ].filter(Boolean).join('\n'));
    }

    async function runActions(actions) {
        for (var i = 0; i < actions.length; i++) {
            var a = actions[i] || {};
            if (a.type === 'navigate') { navigate(a); return; }
            if (a.type === 'open_question') { openQuestion(a.id); return; }
            if (a.type === 'teach') { startTeach(a.question); return; }
            if (a.type === 'solve') { startSolve(a.question); return; }
            if (a.type === 'grade') { openGrade(a); return; }
            if (a.type === 'search_questions') { await runSearch(a); }
            else if (a.type === 'add_to_cart') { await addToCartAction(a); }
            else if (a.type === 'context') { await loadContext(); }
        }
    }

    function updateHomeStats(ctx) {
        var map = {
            statQuestions: 'total_questions',
            statWrong: 'wrong_questions',
            statMastered: 'patterns_mastered',
            statDue: 'due_reviews',
            statPractice: 'practice_records'
        };
        for (var id in map) {
            var el = document.getElementById(id);
            if (el && ctx && ctx[map[id]] !== undefined) el.textContent = ctx[map[id]];
        }
        var cartEl = document.getElementById('statCart');
        if (cartEl) cartEl.textContent = readCart().length;
    }

    function sendMessage(text) {
        if (state.busy || !text.trim()) return;
        state.busy = true;
        if (sendBtn) sendBtn.disabled = true;
        addMessage('user', text.trim());
        var wait = addMessage('agent', '正在处理…');
        fetch(API_BASE + '/agent/act', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text.trim() })
        })
            .then(function (r) { return r.json(); })
            .then(async function (data) {
                var bubble = wait.querySelector('.agent-bubble');
                bubble.textContent = data.reply || '好的';
                if (data.actions && data.actions.length) await runActions(data.actions);
                if (data.context) updateHomeStats(data.context);
            })
            .catch(function () {
                var bubble = wait.querySelector('.agent-bubble');
                bubble.textContent = '连接后端失败，请确认服务已启动。';
            })
            .finally(function () {
                state.busy = false;
                if (sendBtn) sendBtn.disabled = false;
            });
    }

    function addQuickChips(container) {
        ['打开题库', '拿3道解析几何大题', '我该学什么', '打开组卷', '打开巩固日历'].forEach(function (cmd) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.textContent = cmd;
            btn.addEventListener('click', function () {
                if (inputEl) {
                    inputEl.value = cmd;
                    inputEl.style.height = 'auto';
                }
                sendMessage(cmd);
            });
            container.appendChild(btn);
        });
    }

    function buildPanel(host, floating) {
        host.classList.add('agent-host');
        var panel = document.createElement('div');
        panel.className = 'agent-panel' + (floating ? ' agent-panel-float' : '');
        panel.innerHTML =
            '<div class="agent-panel-head">' +
            '<div class="agent-panel-title"><span class="agent-dot"></span>全局教练</div>' +
            (floating ? '<button class="agent-close" type="button" aria-label="关闭">×</button>' : '') +
            '</div>' +
            '<div class="agent-messages"></div>' +
            '<div class="agent-quick"></div>' +
            '<div class="agent-input-row">' +
            '<textarea class="agent-input" rows="1" placeholder="例如：拿3道解析几何大题"></textarea>' +
            '<button class="agent-send" type="button">发送</button>' +
            '</div>';
        host.appendChild(panel);

        messagesEl = panel.querySelector('.agent-messages');
        inputEl = panel.querySelector('.agent-input');
        sendBtn = panel.querySelector('.agent-send');
        var closeBtn = panel.querySelector('.agent-close');
        var quickEl = panel.querySelector('.agent-quick');

        if (closeBtn) {
            closeBtn.addEventListener('click', function () { host.classList.remove('agent-open'); });
        }
        inputEl.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submit();
            }
        });
        inputEl.addEventListener('input', function () {
            inputEl.style.height = 'auto';
            inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
        });
        sendBtn.addEventListener('click', submit);
        addQuickChips(quickEl);
        addMessage('agent', '你好，我是你的全局教练。可以直接说“打开题库”“拿3道解析几何大题”“我该学什么”。');

        function submit() {
            var text = inputEl.value.trim();
            if (!text || state.busy) return;
            inputEl.value = '';
            inputEl.style.height = 'auto';
            sendMessage(text);
        }

        if (floating) {
            var backdrop = document.createElement('div');
            backdrop.className = 'agent-backdrop';
            host.appendChild(backdrop);
            backdrop.addEventListener('click', function () {
                host.classList.remove('agent-open');
            });
            var launcher = document.createElement('button');
            launcher.type = 'button';
            launcher.className = 'agent-launcher';
            launcher.innerHTML = '<span class="agent-launcher-label">AI 教练</span>';
            host.appendChild(launcher);
            launcher.addEventListener('click', function () {
                host.classList.toggle('agent-open');
                if (host.classList.contains('agent-open')) messagesEl.scrollTop = messagesEl.scrollHeight;
            });
        } else {
            host.classList.add('agent-open');
        }
    }

    function init() {
        injectCss();
        var homeHost = document.getElementById('agentHome');
        if (homeHost) {
            buildPanel(homeHost, false);
        } else {
            var widget = document.createElement('div');
            widget.className = 'agent-widget';
            widget.id = 'agentWidget';
            document.body.appendChild(widget);
            buildPanel(widget, true);
        }
    }

    window.AgentGlobal = {
        send: sendMessage,
        renderQuestions: renderQuestionCards,
        updateStats: updateHomeStats,
        API_BASE: API_BASE
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
