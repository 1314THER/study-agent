/* Only loaded by the isolated visitor app, before any page scripts. */
(function () {
    'use strict';
    var config = window.STUDY_DEMO;
    if (!config || !/^[a-f0-9]{32}$/.test(config.session_id || '')) return;

    var prefix = 'study_demo:' + config.session_id + ':';
    var storageFailed = false;
    var storageWrapperFailed = false;
    var isolatedStorage = {};

    function scopedStorage(nativeStorage) {
        var fallback = Object.create(null);
        function listKeys() {
            if (!nativeStorage) return Object.keys(fallback);
            var keys = [];
            for (var i = 0; i < nativeStorage.length; i++) {
                var key = nativeStorage.key(i);
                if (key !== null && key.indexOf(prefix) === 0) keys.push(key.slice(prefix.length));
            }
            return keys;
        }
        var storage = {};
        Object.defineProperties(storage, {
            getItem: { value: function (key) {
                key = String(key);
                return nativeStorage ? nativeStorage.getItem(prefix + key) :
                    (Object.prototype.hasOwnProperty.call(fallback, key) ? fallback[key] : null);
            } },
            setItem: { value: function (key, value) {
                key = String(key);
                value = String(value);
                if (nativeStorage) nativeStorage.setItem(prefix + key, value);
                else fallback[key] = value;
            } },
            removeItem: { value: function (key) {
                if (nativeStorage) nativeStorage.removeItem(prefix + String(key));
                else delete fallback[String(key)];
            } },
            clear: { value: function () {
                listKeys().forEach(function (key) { storage.removeItem(key); });
            } },
            key: { value: function (index) {
                index = Number(index) >>> 0;
                var keys = listKeys();
                return index < keys.length ? keys[index] : null;
            } },
            length: { get: function () { return listKeys().length; } }
        });
        return storage;
    }

    ['localStorage', 'sessionStorage'].forEach(function (name) {
        var nativeStorage = null;
        try { nativeStorage = window[name]; } catch (e) { storageFailed = true; }
        isolatedStorage[name] = scopedStorage(nativeStorage);
        try {
            Object.defineProperty(window, name, {
                configurable: true,
                value: isolatedStorage[name]
            });
        } catch (e) {
            storageWrapperFailed = true;
        }
    });

    var nativeFetch = window.fetch.bind(window);
    var pendingNotice = null;
    var toastTimer = null;
    function startFresh() { window.location.replace('/home.html'); }

    function notice(message, restart) {
        if (!document.body) {
            pendingNotice = { message: message, restart: restart };
            return;
        }
        var toast = document.getElementById('demo-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'demo-toast';
            toast.className = 'demo-toast';
            toast.setAttribute('role', 'status');
            toast.setAttribute('aria-live', 'polite');
            document.body.appendChild(toast);
        }
        toast.replaceChildren();
        var text = document.createElement('span');
        text.textContent = message;
        toast.appendChild(text);
        if (restart) {
            var button = document.createElement('button');
            button.type = 'button';
            button.textContent = '重新进入';
            button.addEventListener('click', startFresh);
            toast.appendChild(button);
        }
        toast.hidden = false;
        window.clearTimeout(toastTimer);
        if (!restart) toastTimer = window.setTimeout(function () { toast.hidden = true; }, 7000);
    }

    window.fetch = function (input, init) {
        var url = new URL(input instanceof Request ? input.url : input, window.location.href);
        var options = init;
        if (url.origin === window.location.origin) {
            options = Object.assign({}, init || {});
            options.headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
            options.headers.set('X-Demo-Session', config.session_id);
        }
        return nativeFetch(input, options).then(function (response) {
            if (url.origin === window.location.origin && (response.status === 401 || response.status === 403)) {
                response.clone().json().then(function (body) {
                    var error = body && body.error;
                    if (error === 'demo_ai_disabled') {
                        notice('本次演示未开放 AI 生成。可以继续查看已有解析、编辑题目和组卷。', false);
                    } else if (error === 'demo_settings_locked') {
                        notice('游客不能修改系统连接配置，题库内容可以正常编辑。', false);
                    } else if (error === 'demo_session_expired' || error === 'demo_session_required') {
                        notice('本次体验已结束或已在其他页面重置，请重新进入。', true);
                    }
                }).catch(function () {});
            }
            return response;
        });
    };

    function makeBanner(main) {
        var banner = document.createElement('section');
        banner.className = 'demo-banner';
        banner.setAttribute('aria-label', '游客体验说明');
        banner.innerHTML = '<div class="demo-banner-copy"><div class="demo-banner-heading">' +
            '<strong>游客体验</strong><span id="demo-time-left"></span>' +
            (config.ai_enabled ? '<span class="demo-ai-status">AI 已开放</span>' : '') + '</div>' +
            '<p>' + (config.ai_enabled ? '题库修改与 AI 生成只保留在本次体验中，不会进入主人的题库。' :
                '修改只保留在本次体验中，不会进入主人的题库。') + '</p></div>' +
            '<div class="demo-banner-actions"><button type="button" id="demo-reset">重新开始</button>' +
            '<button type="button" id="demo-tour-toggle">体验引导</button>' +
            '<a href="/home.html">体验首页</a></div>';
        main.insertBefore(banner, main.firstChild);
        var time = banner.querySelector('#demo-time-left');
        var reset = banner.querySelector('#demo-reset');
        banner.querySelector('#demo-tour-toggle').addEventListener('click', function () { window.StudyDemoTour.start(); });
        var expiresAt = Date.parse(config.expires_at);

        function updateTime() {
            var minutes = Math.max(0, Math.ceil((expiresAt - Date.now()) / 60000));
            if (!Number.isFinite(minutes)) {
                time.textContent = '临时体验';
            } else if (!minutes) {
                time.textContent = '体验已到期';
                reset.textContent = '开始新体验';
            } else {
                var hours = Math.floor(minutes / 60);
                time.textContent = '剩余 ' + (hours ? hours + ' 小时 ' : '') + (minutes % 60 ? minutes % 60 + ' 分钟' : '');
            }
        }
        updateTime();
        window.setInterval(updateTime, 30000);
        reset.addEventListener('click', async function () {
            if (Number.isFinite(expiresAt) && Date.now() >= expiresAt) { startFresh(); return; }
            if (!window.confirm('会清除本次体验中的修改，并恢复演示题库。继续吗？')) return;
            reset.disabled = true;
            reset.textContent = '正在重置…';
            try {
                var response = await window.fetch('/demo/reset', { method: 'POST' });
                if (!response.ok) throw new Error('reset failed');
                try { isolatedStorage.localStorage.clear(); } catch (ignore) {}
                try { isolatedStorage.sessionStorage.clear(); } catch (ignore) {}
                startFresh();
            } catch (e) {
                notice('暂时无法重新开始，请稍后重试或刷新页面。', false);
                reset.disabled = false;
                reset.textContent = '重新开始';
            }
        });
    }

    function addHomeGuide() {
        var container = document.querySelector('.home-container');
        if (!container) return;
        var guide = document.createElement('details');
        guide.className = 'demo-guide';
        guide.innerHTML = '<summary>第一次来？跟着提示体验<span>可收起</span></summary>' +
            '<p class="demo-guide-foot">解一道题 → 等待时看题库、组卷与集合首关 → 回到解析，试着自己作答。</p>' +
            '<div class="demo-guide-buttons"><button type="button" id="demo-tour-start">开始逐步体验</button>' +
            '<button type="button" id="demo-tour-restart">重新看引导</button></div>';
        guide.querySelector('#demo-tour-start').addEventListener('click', function () { window.StudyDemoTour.start(); });
        guide.querySelector('#demo-tour-restart').addEventListener('click', function () { window.StudyDemoTour.restart(); });
        try { guide.open = window.localStorage.getItem('guide_collapsed') !== '1'; }
        catch (e) { guide.open = true; }
        guide.addEventListener('toggle', function () {
            try { window.localStorage.setItem('guide_collapsed', guide.open ? '0' : '1'); } catch (e) {}
        });
        var subtitle = container.querySelector('.home-subtitle');
        if (subtitle) subtitle.after(guide);
        else container.prepend(guide);
    }

    function addPageNote(main) {
        var page = location.pathname.split('/').pop();
        var aiPages = ['', 'home.html', 'demo-home.html', 'teach.html', 'multimodal.html', 'grade.html',
            'loop.html', 'history.html', 'exam.html', 'mother.html', 'board.html'];
        if (page !== 'settings.html' && aiPages.indexOf(page) < 0) return;
        var note = document.createElement('p');
        note.className = 'demo-page-note';
        note.textContent = page === 'settings.html' ?
            '游客不能修改系统连接配置。题库内容可以自由编辑。' :
            (config.ai_enabled ? '可以体验 AI 解题、教学和生成。保存的题目与学习记录仅保留在本次体验中。' :
                '本次演示未开放 AI 生成。可以查看已有解析、编辑题目、组卷和安排复习。');
        var banner = main.querySelector('.demo-banner');
        if (banner) banner.after(note);
        else main.prepend(note);
    }

    function addHomeFooter(main) {
        var page = location.pathname.split('/').pop();
        if (page !== '' && page !== 'home.html' && page !== 'demo-home.html') return;
        var footer = document.createElement('footer');
        footer.className = 'demo-footer';
        footer.innerHTML = '<div>渝ICP备2026024246号-1</div>' +
            '<a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">备案信息查询</a>';
        main.appendChild(footer);
    }

    var presetItems = [];
    var presetId = 'national-2025-q16';
    var presetPromise = null;
    function currentPreset() { return presetItems.find(function (p) { return p.id === presetId; }) || null; }
    function unchangedPreset(question) {
        var selected = currentPreset();
        var text = question === undefined && window._questions ? (window._questions[window._selectedIdx] || {}).latex : question;
        return !!selected && String(text).trim() === selected.question.trim();
    }
    function loadPresets() {
        if (!presetPromise) presetPromise = window.fetch('/demo/presets').then(function(response){
            if (!response.ok) throw new Error('例题暂时无法加载，请刷新重试。');
            return response.json();
        }).then(function(data){presetItems=Array.isArray(data)?data:data.presets||[];presetId=data.default_id||presetId;return {presets:presetItems,default_id:presetId};}).catch(function(error){presetPromise=null;throw error;});
        return presetPromise;
    }
    window.StudyDemoPresets = {
        load: loadPresets,
        selected: currentPreset,
        isUnchanged: unchangedPreset,
        idForQuestion: function (question) {var item=presetItems.find(function(p){return String(question).trim()===p.question.trim();});return item?item.id:null;},
        use: function (id) {
            var item = presetItems.find(function (p) { return p.id === id; });
            if (!item || typeof window.selectDemoPreset!=='function') return false;
            presetId = id;
            return window.selectDemoPreset(id);
        }
    };
    var tourKey = 'demo_action_tour_v4';
    var tourState = {};
    try { tourState = JSON.parse(window.localStorage.getItem(tourKey) || '{}') || {}; } catch (ignore) {}
    var tourPanel = null;
    var tourTarget = null;
    var tourTimer = null;
    var tourRenderedStep = null;
    var tourSteps = [
        {id:'welcome', page:'home.html', target:'#demo-intro', read:true, title:'一起体验一次学习过程', text:'三道近年高考大题已经备好。先认识多模态解答，再浏览题库、组卷与集合首关，最后看看解析与教学。每一步都能跳过，跳过不会调用 AI。'},
        {id:'open-solve', page:'home.html', target:'#demo-enter-multimodal', click:true, title:'进入多模态解答', text:'请点击“进入多模态解答”。这里可以直接解预设真题，也可以上传图片、PDF 或文档。'},
        {id:'preset', page:'multimodal.html', target:'.mm-qcard[data-preset-id="national-2025-q16"]', event:'study:preset-selected', title:'选择一道中档大题', text:'三道题已经在左栏：数列与导数、解三角形、对数函数。请点击默认的数列题卡，在右侧查看和编辑题干，并核对原题出处。'},
        {id:'save', page:'multimodal.html', target:function(){return mmTarget('.demo-auto-save');}, read:true, title:'保留这次解答', text:'“自动加入本次题库”默认开启，完成的解析会保存到本次体验题库。这里的题干可以编辑，修改后按自定义题处理。'},
        {id:'submit', page:'multimodal.html', target:function(){return '.mm-demo-submit[data-index="'+(tourState.client_index||0)+'"]';}, event:'studyjobsubmitted', title:'开始解题', text:'请点击“开始解题”，真实 AI 任务会在服务器执行。切页与刷新不会中断；也可以跳过这一步，继续了解功能。'},
        {id:'wait-library', page:'multimodal.html', target:'.nav-item[data-page="history"]', click:true, title:'等待时，先看看题库', text:'请点击“个人题库”。已经提交的解题会继续进行；没有提交也能浏览已经准备好的题目与解析。'},
        {id:'library-open', page:'history.html', target:function(){ return '.history-card .hc-preview'; }, click:true, title:'打开一张题目卡片', text:'这里已经准备了演示题。请点击一张卡片，看看题干和解析。刚才的新题完成后，也会出现在本次题库中。'},
        {id:'library-detail', page:'history.html', target:'#detailResult', read:true, title:'解析也能随时找回', text:'这里可以回看每一步的解法，也能展开详细过程、记录自己错在哪。现在先认识这一页。'},
        {id:'library-back', page:'history.html', target:'#detailView .back-btn', click:true, title:'回到题目列表', text:'请点击“返回列表”，接着把刚才这道题放进组卷篮子。'},
        {id:'library-cart', page:'history.html', target:function(){ return '.history-card' + (tourState.library_id ? '[data-id="' + tourState.library_id + '"]' : '') + ' button[title="加入组卷"]'; }, click:true, title:'选一道题加入组卷', text:'请点击卡片上的“加入组卷”按钮。右上角的组卷数量会更新。'},
        {id:'open-exam', page:'history.html', target:'#goExamBtn', click:true, title:'打开试卷', text:'请点击“前往组卷”，看看选中的题怎样排进一张试卷。'},
        {id:'exam-mode', page:'exam.html', target:'.exam-mode-btn[data-mode="teacher"]', click:true, title:'切换教师版', text:'请点击“教师版”。学生版用于作答，教师版会显示答案与解析。'},
        {id:'exam-preview', page:'exam.html', target:'#examPreview', read:true, title:'题目可以组成试卷', text:'这里是试卷预览。可以修改标题、调整顺序和答题空间，也可以导出学生版或教师版。导出不是这次体验的必做步骤。'},
        {id:'open-board', page:'exam.html', target:'.nav-item[data-page="board"]', click:true, title:'再看看学习路线', text:'请点击“闯关”。当前可以体验集合板块的路线与首关概念判断。'},
        {id:'board-route', page:'board.html', target:'.run-board-head', read:true, title:'关卡把方法排成路线', text:'集合板块位于目录最后，已经默认选中。这里展示 21 项方法主题；其他板块和后续练习尚未完成。'},
        {id:'board-open', page:'board.html', target:'.demo-board-open', event:'study:board-mission-opened', title:'打开首关', text:'请点击“打开首关要点”，先认识集合的确定性、互异性与无序性。'},
        {id:'board-question-one', page:'board.html', target:'#demo-concept-0', event:'study:board-concept-answered', index:0, title:'试一道概念判断', text:'“很大的数”能明确判断哪些数属于它吗？请点击一个答案，看看反馈。'},
        {id:'board-question-two', page:'board.html', target:'#demo-concept-1', event:'study:board-concept-answered', index:1, title:'再判断一次', text:'如果元素只是换了排列顺序，集合会变吗？请点击一个答案。'},
        {id:'board-finish', page:'board.html', target:'#demo-board-read', event:'study:board-concepts-viewed', title:'完成首关体验', text:'完成两道判断后，可以点击这里返回路线。这只记录体验过程，不代表已经掌握或通关。'},
        {id:'return-result', page:'board.html', target:'.run-board-head', result:true, title:'回到刚才的解答', text:'解题任务完成后，请点击下方“回到解答”。如果仍在进行，可以先自由浏览，完成提示会保留。'},
        {id:'result-detail', page:'multimodal.html', target:function(){return mmTarget('.detail-toggle');}, click:true, title:'看清一步为什么这样做', text:'请展开一个详细过程。标准过程方便回顾，详细过程帮助理解推理。如果结果来自预先准备的示例解析，页面会明确标注。'},
        {id:'result-read', page:'multimodal.html', target:function(){return '#session_'+(tourState.client_index||0);}, read:true, title:'认识解析与难度', text:'解析按照步骤展示。难度图描述计算量、分类讨论等方面；它帮助选择练习重点，不等于你的掌握程度。'},
        {id:'open-teach', page:'multimodal.html', target:function(){return mmTarget('[data-demo-teach]');}, click:true, title:'试着自己做一遍', text:'请点击“手把手教学”。老师会围绕这道题提问，你可以自己作答，或在卡住时求一点提示。跳过可以直接继续认识教学页面。'},
        {id:'teach-prepare', page:'teach.html', target:'#teacherModalConfirm, #teachStartBtn', click:true, title:'准备开始教学', text:'如果出现老师选择，请先保持默认老师，点击“确定，开始解题”。教学任务准备好后，会出现第一个问题。'},
        {id:'teach-answer', page:'teach.html', target:'#teachChatInput', event:'study:teach-answer-feedback', title:'回答当前这一步', text:'先读老师的问题，在这里写下自己的想法，再点击发送。不会时可以输入“给我一点提示”。有反馈后，引导会继续。'},
        {id:'finished', page:null, target:'.demo-banner', read:true, title:'教程完成，接下来由你探索', text:'你已经认识多模态解答、题库、组卷、集合首关与教学。可以留在这里自由体验，也可以直接前往 150.chat。AI 改卷、母题看板、套路循环和关卡编辑仍在开发中。'}
    ];
    function mmTarget(suffix){return '#session_'+(tourState.client_index||0)+' '+suffix;}

    function saveTour() { try { window.localStorage.setItem(tourKey, JSON.stringify(tourState)); } catch (ignore) {} }
    function currentTourStep() { return tourSteps.find(function(s){return s.id === tourState.step;}) || tourSteps[0]; }
    function clearTourHighlight() {
        if (tourTarget) tourTarget.classList.remove('demo-tour-highlight');
        tourTarget = null;
    }
    function visible(element) { return element && !element.hidden && !!element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden'; }
    function pageName() {var page=location.pathname.split('/').pop();return !page||page==='demo-home.html'?'home.html':page;}
    function selectorFor(step) { return typeof step.target === 'function' ? step.target() : step.target; }
    function moveTour(delta) {
        var index = tourSteps.indexOf(currentTourStep());
        var next = tourSteps[index + delta];
        if (!next) { completeTour(); return; }
        tourState.step = next.id;
        saveTour();
        tourRenderedStep = null;
        renderTour();
    }
    function stopTour() {
        if(!tourState.completed)return false;
        tourState.active = false;
        tourState.seen = true;
        saveTour();
        clearTourHighlight();
        if (tourPanel) tourPanel.hidden = true;
        return true;
    }
    function completeTour(){
        tourState.completed=true;saveTour();stopTour();
        var complete=document.getElementById('demo-home-complete');if(complete)complete.hidden=false;
    }
    function startTour(reset) {
        if (reset) tourState = {seen:true,completed:false};
        tourState.active = true;
        tourState.seen = true;
        var complete=document.getElementById('demo-home-complete');if(complete)complete.hidden=!tourState.completed;
        if (!tourState.step) tourState.step = pageName() === 'multimodal.html' ? 'preset' : 'welcome';
        saveTour();
        tourRenderedStep = null;
        renderTour();
    }
    function rememberJob(job) {
        if (!job || job.kind !== 'solve') return;
        if (tourState.job_id && job.job_id !== tourState.job_id) return;
        tourState.job_id = job.job_id;
        tourState.job_status = job.status;
        if (job.result) {
            tourState.question_id = job.result.saved_question_id || job.result.question_id || tourState.question_id;
            tourState.result_ready = job.status === 'completed' || job.status === 'succeeded' || job.status === 'done';
        }
        saveTour();
    }
    function consumeTourEvent(name, detail) {
        if (name === 'studyjobsubmitted' && detail && detail.kind === 'solve') {
            if (tourState.active && currentTourStep().id === 'submit') {
                tourState.job_id = detail.job_id;
                tourState.client_index=detail.args&&detail.args.client_index||0;
                tourState.result_ready = false;
                rememberJob(detail);
                moveTour(1);
            }
        } else if (name === 'studyjobupdate' || name === 'studyjobdone') {
            rememberJob(detail);
            if (name === 'studyjobdone' && detail && detail.kind === 'teach_chat' && detail.status === 'done') tourState.awaiting_teach_feedback = true;
        }
        else if (name === 'study:multimodal-solve-ready') {
            if(detail&&detail.client_index!==undefined&&detail.client_index!==(tourState.client_index||0))return;
            tourState.result_ready = true;
            var result = detail && (detail.result || detail);
            if (result) tourState.question_id = result.saved_question_id || result.question_id || tourState.question_id;
            saveTour();
        } else if (name === 'study:teach-opened' && tourState.awaiting_teach_feedback && currentTourStep().id === 'teach-answer') {
            tourState.awaiting_teach_feedback = false;
            moveTour(1);
        }
        if(name==='study:preset-selected'&&detail&&detail.client_index!==undefined)tourState.client_index=detail.client_index;
        var step = currentTourStep();
        if (tourState.active && step.event === name && name !== 'studyjobsubmitted') {
            if (step.index === undefined || (detail && Number(detail.index) === step.index)) moveTour(1);
        }
        if (tourState.active) renderTour();
    }
    window.StudyDemoTour = {
        start: function(){startTour(false);}, restart: function(){startTour(true);},
        skip: function(){moveTour(1);}, stop: stopTour, emit: consumeTourEvent
    };

    function addTourButton(container, label, handler, secondary) {
        var button = document.createElement('button');
        button.type = 'button';
        button.className = secondary ? 'secondary' : '';
        button.textContent = label;
        button.addEventListener('click', handler);
        container.appendChild(button);
        return button;
    }
    function renderTour() {
        if (!tourState.active || !document.body) return;
        var step = currentTourStep();
        if (!tourPanel) {
            tourPanel = document.createElement('aside');
            tourPanel.id = 'demo-tour-panel';
            tourPanel.className = 'demo-tour-panel';
            tourPanel.setAttribute('role', 'region');
            tourPanel.setAttribute('aria-label', '逐步体验引导');
            document.body.appendChild(tourPanel);
        }
        tourPanel.hidden = false;
        var correctPage = !step.page||pageName() === step.page;
        if (correctPage && step.id === 'teach-prepare' && visible(document.getElementById('teachChatInput'))) { moveTour(1); return; }
        var selector = correctPage ? selectorFor(step) : '.nav-item[href*="' + step.page + '"]';
        var target = Array.from(document.querySelectorAll(selector)).find(visible) || null;
        var needsMenu = !target && selector.indexOf('.nav-item') >= 0;
        if (needsMenu) target = Array.from(document.querySelectorAll('.mobile-nav-toggle')).find(visible) || null;
        tourState.needs_menu = !!(needsMenu && target);
        if (target !== tourTarget) {
            clearTourHighlight();
            tourTarget = target;
            if (target) target.classList.add('demo-tour-highlight');
        }
        var renderKey = step.id + ':' + correctPage + ':' + !!target + ':' + !!tourState.result_ready + ':' + tourState.job_status + ':' + tourState.needs_menu;
        if (tourRenderedStep !== renderKey) {
            tourPanel.replaceChildren();
            var counter = document.createElement('small');
            counter.textContent = '体验引导 ' + (tourSteps.indexOf(step) + 1) + ' / ' + tourSteps.length;
            var title = document.createElement('h2'); title.textContent = step.title;
            var text = document.createElement('p'); text.textContent = step.text;
            if (tourState.needs_menu) text.textContent = '先点击左上角打开导航。' + step.text;
            tourPanel.append(counter, title, text);
            var actions = document.createElement('div'); actions.className = 'demo-tour-actions';
            if (!correctPage) {
                var link = document.createElement('a');
                link.className = 'demo-tour-go'; link.href = step.page;
                link.textContent = '前往这一步'; actions.appendChild(link);
            } else if (step.result) {
                var resultLink = document.createElement('a');
                resultLink.id = 'demo-return-result'; resultLink.className = 'demo-tour-go';
                var jobFailed = ['error','interrupted','failed'].indexOf(tourState.job_status) >= 0;
                resultLink.textContent = tourState.result_ready ? '回到解答 →' : (jobFailed ? '回到解答重试' : '解题进行中，可以继续浏览');
                if (tourState.result_ready) {
                    resultLink.href = 'multimodal.html' + (tourState.job_id ? '?job=' + encodeURIComponent(tourState.job_id) : '');
                    resultLink.addEventListener('click', function(){moveTour(1);});
                } else if (jobFailed) {
                    resultLink.href = 'multimodal.html';
                    resultLink.addEventListener('click', function(){
                        tourState.step = 'submit'; tourState.job_id = null; tourState.job_status = null; saveTour();
                    });
                } else resultLink.setAttribute('aria-disabled', 'true');
                actions.appendChild(resultLink);
            } else if(step.id==='finished'){
                var ownerLink=document.createElement('a');ownerLink.className='demo-tour-go';ownerLink.href='https://150.chat/';ownerLink.textContent='前往 150.chat →';ownerLink.addEventListener('click',completeTour);actions.appendChild(ownerLink);
                addTourButton(actions,'完成教程，自由体验',completeTour);
            } else if (step.read && target) {
                addTourButton(actions,'知道了，继续',function(){moveTour(1);});
            } else if (!target) {
                var waiting = document.createElement('p'); waiting.className = 'demo-tour-wait';
                waiting.textContent = '等待当前内容准备好。可以跳过这一步继续，跳过不会调用 AI。';
                tourPanel.appendChild(waiting);
            }
            if (tourSteps.indexOf(step) > 0) addTourButton(actions, '上一步', function(){moveTour(-1);}, true);
            if(step.id!=='finished')addTourButton(actions, '跳过这步', function(){moveTour(1);}, true);
            if(tourState.completed)addTourButton(actions, '收起教程', stopTour, true);
            tourPanel.appendChild(actions);
            tourRenderedStep = renderKey;
            if (target && correctPage) target.scrollIntoView({behavior:'smooth', block:'center'});
        }
        positionTour();
    }
    function positionTour() {
        if (!tourPanel || tourPanel.hidden) return;
        var width = Math.min(360, window.innerWidth - 28);
        tourPanel.style.width = width + 'px';
        var height = tourPanel.getBoundingClientRect().height;
        var left = window.innerWidth - width - 20;
        var top = window.innerHeight - height - 20;
        if (tourTarget && window.innerWidth > 700 && tourTarget.matches('.demo-preset-card')) {
            var presetGrid = document.getElementById('demo-preset-grid') || tourTarget;
            var presetRect = presetGrid.getBoundingClientRect();
            left = presetRect.left;
            top = presetRect.bottom + 10;
            if (top + height > window.innerHeight - 14) top = window.innerHeight - height - 14;
        } else if (tourTarget && window.innerWidth > 700) {
            var rect = tourTarget.getBoundingClientRect();
            if (rect.width < 500) {
                left = rect.right + 16;
                if (left + width > window.innerWidth - 14) left = rect.left - width - 16;
                top = rect.top;
            } else {
                left = rect.left;
                top = rect.bottom + 12;
                if (top + height > window.innerHeight - 14) top = rect.top - height - 12;
            }
        } else if (tourTarget) {
            var mobileRect = tourTarget.getBoundingClientRect();
            if ((mobileRect.top + mobileRect.bottom) / 2 > window.innerHeight / 2) top = 14;
        }
        tourPanel.style.left = Math.max(14, Math.min(left, window.innerWidth - width - 14)) + 'px';
        tourPanel.style.top = Math.max(14, Math.min(top, window.innerHeight - height - 14)) + 'px';
    }
    function initializeTour() {
        ['studyjobsubmitted','studyjobupdate','studyjobdone','study:multimodal-solve-ready','study:teach-answer-feedback','study:teach-opened','study:preset-selected',
            'study:board-mission-opened','study:board-concept-answered','study:board-concepts-viewed'].forEach(function(name){
            document.addEventListener(name, function(e){consumeTourEvent(name,e.detail);});
        });
        document.addEventListener('click', function(event){
            if (!tourState.active || !tourTarget || !tourTarget.contains(event.target)) return;
            var step = currentTourStep();
            if (!step.click || pageName() !== step.page) return;
            if (tourState.needs_menu) return;
            if (step.id === 'library-open') {
                var card = event.target.closest('.history-card');
                if (card) tourState.library_id = Number(card.dataset.id);
            }
            if (step.id === 'open-teach') {
                tourState.step = 'teach-prepare'; saveTour();
                clearTourHighlight(); if (tourPanel) tourPanel.hidden = true;
                return;
            }
            // Persist the next step before a normal link click unloads this page.
            moveTour(1);
        }, true);
        window.addEventListener('resize', positionTour);
        window.addEventListener('scroll', positionTour, true);
        window.addEventListener('storage', function(event){
            if (event.key !== prefix + tourKey) return;
            try { tourState = JSON.parse(event.newValue || '{}') || {}; } catch (ignore) { return; }
            var complete=document.getElementById('demo-home-complete');if(complete)complete.hidden=!tourState.completed;
            tourRenderedStep = null;
            if (!tourState.active) {clearTourHighlight(); if(tourPanel)tourPanel.hidden=true;}
            else renderTour();
        });
        tourTimer = window.setInterval(renderTour, 600);
        if (!tourState.completed) startTour(false);
        else renderTour();
        var complete=document.getElementById('demo-home-complete');if(complete)complete.hidden=!tourState.completed;
    }

    function displayCategory(value){return String(value).replace(/指对幂耐克函数/g,'指数、对数与幂函数');}
    window.StudyDemoDisplay={category:displayCategory};
    function initializeDemoDisplay(){
        function normalize(root){
            if(!root)return;
            var links=[];if(root.nodeType===1&&root.matches('a[href]'))links.push(root);
            if(root.querySelectorAll)links=links.concat(Array.from(root.querySelectorAll('a[href]')));
            links.forEach(function(a){try{
                var url=new URL(a.getAttribute('href'),location.href);
                if(url.origin!==location.origin||!/(?:^|\/)index\.html$/.test(url.pathname))return;
                var nav=a.closest('nav'),existing=nav&&nav.querySelector('a[data-page="multimodal"]');
                if(existing&&existing!==a&&a.dataset.page==='solve'){a.remove();return;}
                url.pathname=url.pathname.replace(/index\.html$/,'multimodal.html');a.href=url.pathname+url.search+url.hash;
                if(a.dataset.page==='solve')a.dataset.page='multimodal';
                a.title=(a.title||'').replace(/单题解答/g,'多模态解答');
                if(a.textContent.includes('单题解答'))a.textContent=a.textContent.replace(/单题解答/g,'多模态解答');
            }catch(ignore){}});
            if(root.querySelectorAll)root.querySelectorAll('[onclick]').forEach(function(button){var value=button.getAttribute('onclick');if(value&&/index\.html/.test(value))button.setAttribute('onclick',value.replace(/index\.html/g,'multimodal.html'));});
            var texts=[];
            if(root.nodeType===3)texts.push(root);
            else if(document.createTreeWalker){var walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);while(walker.nextNode())texts.push(walker.currentNode);}
            texts.forEach(function(text){
                var parent=text.parentElement;if(!parent||parent.closest('script,style,textarea'))return;
                if(parent.tagName==='OPTION'&&!parent.hasAttribute('value'))return;
                var clean=displayCategory(text.nodeValue);if(clean!==text.nodeValue)text.nodeValue=clean;
            });
        }
        normalize(document.body);
        if(typeof MutationObserver!=='undefined')new MutationObserver(function(changes){changes.forEach(function(change){if(change.type==='characterData')normalize(change.target);else change.addedNodes.forEach(normalize);});}).observe(document.body,{subtree:true,childList:true,characterData:true});
    }

    document.addEventListener('DOMContentLoaded', function () {
        var style = document.createElement('link');
        style.rel = 'stylesheet';
        style.href = '/demo-session.css?v=20261009a';
        document.head.appendChild(style);
        var main = document.querySelector('.main-content') || document.querySelector('main') || document.body;
        makeBanner(main);
        addHomeGuide();
        addPageNote(main);
        addHomeFooter(main);
        initializeDemoDisplay();
        initializeTour();
        if (storageWrapperFailed) notice('当前浏览器无法区分不同体验的页面状态，请改用最新版 Safari、Chrome 或 Edge。', false);
        else if (storageFailed) notice('浏览器限制了本地保存，部分页面状态在刷新后可能丢失。建议使用 Safari、Chrome 或 Edge 的普通窗口。', false);
        if (pendingNotice) { notice(pendingNotice.message, pendingNotice.restart); pendingNotice = null; }
    });
})();
