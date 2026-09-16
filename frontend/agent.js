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
    var chatHistory = [];
    var MAX_HISTORY = 20; // 10 轮对话
    var lastSearch = [];
    var hostEl = null;
    var messagesEl = null;
    var inputEl = null;
    var sendBtn = null;

    function injectCss() {
        if (document.querySelector('link[data-agent-css]')) return;
        var link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = 'agent.css?v=20260809g';
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
        if (role === 'agent') {
            bubble.innerHTML = escapeHtml(String(text == null ? '' : text));
            ensureKatex(function () { renderMath(bubble); });
        } else {
            bubble.textContent = text;
        }
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
            loop: 'loop.html', calendar: 'calendar.html', board: 'board.html', 'level-editor': 'level-editor.html'
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

    function pushHistory(role, content) {
        content = String(content == null ? '' : content).trim();
        if (!content) return;
        chatHistory.push({ role: role, content: content });
        if (chatHistory.length > MAX_HISTORY) chatHistory.splice(0, chatHistory.length - MAX_HISTORY);
    }

    function renderSolveBlock(block, body) {
        var card = document.createElement('div');
        card.className = 'agent-qcard';
        var html = '<div class="agent-qmeta">' +
            escapeHtml(block.category || '') +
            (block.difficulty_level ? ' · ' + escapeHtml(block.difficulty_level) : '') +
            '</div>';
        html += '<div class="agent-qtext">' + escapeHtml(block.question || '') + '</div>';
        if (block.final_answer) {
            html += '<div class="agent-solve-answer"><span class="agent-block-label">答案</span><div>' +
                escapeHtml(block.final_answer) + '</div></div>';
        }
        if (block.knowledge_points && block.knowledge_points.length) {
            html += '<div class="agent-solve-kps"><span class="agent-block-label">知识点</span> ' +
                block.knowledge_points.map(escapeHtml).join('、') + '</div>';
        }
        if (block.qid) {
            html += '<div class="agent-qactions"><button type="button" data-agent-open="' + block.qid + '">查看完整解析</button></div>';
        }
        card.innerHTML = html;
        var btn = card.querySelector('button[data-agent-open]');
        if (btn) {
            btn.addEventListener('click', function () { openQuestion(block.qid); });
        }
        body.appendChild(card);
        ensureKatex(function () { renderMath(card); });
    }

    function renderTeachBlock(block, body) {
        var card = document.createElement('div');
        card.className = 'agent-qcard';
        var html = '<div class="agent-qmeta">共 ' + (block.total_steps || 0) + ' 步</div>';
        html += '<div class="agent-qtext">' + escapeHtml(block.message || '') + '</div>';
        var titles = (block.step_titles || []).map(function (t) { return '· ' + t; }).join('\n');
        if (titles) html += '<div class="agent-teach-steps">' + escapeHtml(titles) + '</div>';
        html += '<div class="agent-qactions"><button type="button" data-agent-teach="1">进入教学页继续</button></div>';
        card.innerHTML = html;
        var btn = card.querySelector('button[data-agent-teach]');
        if (btn) {
            btn.addEventListener('click', function () { startTeachSession(block); });
        }
        body.appendChild(card);
        ensureKatex(function () { renderMath(card); });
    }

    function renderGradeBlock(block, body) {
        var r = block.result || {};
        var card = document.createElement('div');
        card.className = 'agent-qcard';
        var score = '';
        if (r.earned_score != null && r.full_score != null) score = '得分 ' + r.earned_score + ' / ' + r.full_score;
        var html = '<div class="agent-qmeta">' + escapeHtml(r.question_type || '') +
            (score ? ' · ' + escapeHtml(score) : '') + '</div>';
        html += '<div class="agent-qtext">' + escapeHtml(r.feedback || (r.is_correct ? '回答正确。' : '回答有误。')) + '</div>';
        if (r.expected_answer) {
            html += '<div class="agent-solve-answer"><span class="agent-block-label">参考答案</span><div>' +
                escapeHtml(r.expected_answer) + '</div></div>';
        }
        if (r.step_results && r.step_results.length) {
            html += '<div class="agent-teach-steps">' + r.step_results.map(function (s) {
                var mark = s.is_correct ? '✓' : (s.is_partial ? '△' : '✗');
                return mark + ' ' + escapeHtml(s.title || ('步骤 ' + s.step_number));
            }).join('\n') + '</div>';
        }
        card.innerHTML = html;
        body.appendChild(card);
        ensureKatex(function () { renderMath(card); });
    }

    function renderPlanBlock(block, body) {
        var plan = block.plan || {};
        var card = document.createElement('div');
        card.className = 'agent-qcard';
        var meta = '共 ' + plan.total_patterns + ' 个套路 · 每天 ' + plan.per_day + ' 个 · ' + plan.days + ' 天';
        if (plan.applied_count != null) meta += ' · 已写入日历 ' + plan.applied_count + ' 个';
        var html = '<div class="agent-qmeta">' + escapeHtml(meta) + '</div>';
        var preview = (plan.preview || []).map(function (d) {
            return d.date + '：' + (d.patterns || []).join('、');
        }).join('\n');
        html += '<div class="agent-qtext">' + escapeHtml(preview || '暂时没有可规划的套路。') + '</div>';
        html += '<div class="agent-qactions"><button type="button" data-agent-cal="1">打开巩固日历</button></div>';
        card.innerHTML = html;
        var btn = card.querySelector('button[data-agent-cal]');
        if (btn) {
            btn.addEventListener('click', function () { location.href = 'calendar.html'; });
        }
        body.appendChild(card);
    }

    function renderBlocks(blocks) {
        if (!blocks || !blocks.length) return;
        blocks.forEach(function (block) {
            if (!block || !block.type) return;
            var box = addActionBlock(block.title || '', '');
            var emptyBubble = box.box.querySelector('.agent-bubble');
            if (emptyBubble && !emptyBubble.textContent.trim()) emptyBubble.style.display = 'none';
            if (block.type === 'search') {
                if (block.empty) {
                    box.body.textContent = '没有找到符合条件的题目。';
                } else {
                    renderQuestionCards(block.items || [], box.body);
                }
            } else if (block.type === 'solve') {
                renderSolveBlock(block, box.body);
            } else if (block.type === 'teach') {
                renderTeachBlock(block, box.body);
            } else if (block.type === 'grade') {
                renderGradeBlock(block, box.body);
            } else if (block.type === 'plan') {
                renderPlanBlock(block, box.body);
            } else if (block.type === 'solve_error') {
                box.body.textContent = block.detail || block.title || '执行失败';
            }
        });
    }

    function startTeachSession(block) {
        try {
            var steps = (block.step_titles || []).map(function (title, i) {
                return {
                    chunk_id: 1,
                    chunk_type: '',
                    category: '',
                    step_number: i + 1,
                    title: title || '步骤 ' + (i + 1),
                    standard_writing: '',
                    detailed_writing: '',
                    knowledge_point: '',
                    step_answer: '',
                    step_prompt: i === 0 ? (block.message || '') : ''
                };
            });
            localStorage.setItem('_teach_session_v2', JSON.stringify({
                session_id: block.session_id,
                question: block.question || '',
                teacher: block.teacher || 'liangliang',
                messages: block.message ? [{ role: 'teacher', content: block.message }] : [],
                stats: { correct: 0, wrong: 0, skipped: 0 },
                current_step: 0,
                total_steps: block.total_steps || 0,
                steps: steps,
                chunk_results: [],
                step_errors: {}
            }));
        } catch (e) {}
        location.href = 'teach.html';
    }

    function sendMessage(text) {
        if (state.busy || !text.trim()) return;
        state.busy = true;
        if (sendBtn) sendBtn.disabled = true;
        addMessage('user', text.trim());
        pushHistory('user', text.trim());
        var wait = addMessage('agent', '正在处理…');
        var bubble = wait.querySelector('.agent-bubble');
        var started = false;

        function handleItem(item) {
            if (!item) return;
            if (item.type === 'progress') {
                if (!started) bubble.textContent = item.message || '正在处理…';
            } else if (item.type === 'token') {
                var chunk = item.text || '';
                if (!started) {
                    bubble.textContent = chunk;
                    started = true;
                } else {
                    bubble.textContent += chunk;
                }
                messagesEl.scrollTop = messagesEl.scrollHeight;
            } else if (item.type === 'done' && item.result) {
                var data = item.result;
                var reply = data.reply || '好的';
                bubble.textContent = reply;
                bubble.innerHTML = escapeHtml(reply);
                ensureKatex(function () { renderMath(bubble); });
                pushHistory('assistant', reply);
                renderBlocks(data.blocks || []);
                if (data.context) updateHomeStats(data.context);
                if (data.actions && data.actions.length) runActions(data.actions);
            }
        }

        fetch(API_BASE + '/agent/act', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text.trim(), history: chatHistory.slice(0, -1).slice(-MAX_HISTORY) })
        })
            .then(function (r) {
                if (!r.ok || !r.body) throw new Error('bad response');
                var reader = r.body.getReader();
                var decoder = new TextDecoder('utf-8');
                var buf = '';
                function pump() {
                    return reader.read().then(function (res) {
                        if (res.done) return;
                        buf += decoder.decode(res.value, { stream: true });
                        var lines = buf.split('\n');
                        buf = lines.pop();
                        lines.forEach(function (line) {
                            line = line.trim();
                            if (!line) return;
                            try {
                                handleItem(JSON.parse(line));
                            } catch (e) {}
                        });
                        return pump();
                    });
                }
                return pump();
            })
            .catch(function () {
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
