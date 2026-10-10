(function () {
    'use strict';
    if (window.StudyAuth) return;
    var nativeFetch = window.fetch.bind(window);
    var publicPage = location.pathname === '/' || /\/(?:login|deepseek-guide)\.html$/.test(location.pathname);
    var bootUser = window.STUDY_USER;
    var state = { authenticated: !!bootUser, user: bootUser || null, enabled: true };
    // The account gateway injects STUDY_USER before this script. Legacy local
    // pages keep their existing browser state when that gateway is disabled.
    var storageScope = bootUser ? 'study_user:' + bootUser.id + ':' : '';
    var isDemo = !!window.STUDY_DEMO;
    var storageFallback = Object.create(null);

    // Personal browser state (including the exam basket) follows the signed-in user.
    if (!isDemo && !publicPage) ['localStorage', 'sessionStorage'].forEach(function (name) {
        var nativeStorage;
        try { nativeStorage = window[name]; } catch (ignore) {}
        var fallback = storageFallback[name] = Object.create(null);
        var wrapper = {};
        function keys() {
            if (!nativeStorage) return Object.keys(fallback);
            var result = [];
            var prefix = storageScope;
            for (var i = 0; i < nativeStorage.length; i++) {
                var key = nativeStorage.key(i);
                if (key !== null && key.indexOf(prefix) === 0) result.push(key.slice(prefix.length));
            }
            return result;
        }
        Object.defineProperties(wrapper, {
            getItem: {value: function (key) {
                key = String(key);
                try { return nativeStorage && storageScope !== 'pending:' ? nativeStorage.getItem(storageScope + key) : (fallback[key] || null); }
                catch (ignore) { return fallback[key] || null; }
            }},
            setItem: {value: function (key, value) {
                key = String(key); value = String(value);
                fallback[key] = value;
                try { if (nativeStorage && storageScope !== 'pending:') nativeStorage.setItem(storageScope + key, value); } catch (ignore) {}
            }},
            removeItem: {value: function (key) {
                delete fallback[String(key)];
                try { if (nativeStorage) nativeStorage.removeItem(storageScope + String(key)); } catch (ignore) {}
            }},
            clear: {value: function () { keys().forEach(function (key) { wrapper.removeItem(key); }); }},
            key: {value: function (index) { return keys()[Number(index) >>> 0] || null; }},
            length: {get: function () { return keys().length; }}
        });
        try {
            // Remove secrets cached by the retired provider switcher.
            if (nativeStorage) ['deepseek', 'qwen', 'doubao'].forEach(function (provider) { nativeStorage.removeItem('provider_key_' + provider); });
            Object.defineProperty(window, name, {configurable: true, value: wrapper});
        } catch (ignore) {}
    });

    async function request(path, method, body) {
        var options = {method: method || 'GET', credentials: 'same-origin', cache: 'no-store'};
        if (body !== undefined) { options.headers = {'Content-Type': 'application/json'}; options.body = JSON.stringify(body); }
        var response = await nativeFetch(path, options);
        var data = {};
        try { data = await response.json(); } catch (ignore) {}
        if (!response.ok) {
            var detail = data.detail;
            var message = typeof detail === 'string' ? detail : (data.message || data.error || '请求未完成，请稍后重试。');
            var error = new Error(message);
            error.status = response.status;
            throw error;
        }
        return data;
    }

    function isOwner() { return !!(state.user && state.user.role === 'owner'); }
    function redirectLogin() { if (!publicPage) location.replace('/login.html'); }
    function toast(message) {
        var box = document.getElementById('auth-toast');
        if (!box) { box = document.createElement('div'); box.id = 'auth-toast'; box.className = 'auth-toast'; box.setAttribute('role', 'status'); document.body.appendChild(box); }
        box.textContent = message;
        box.hidden = false;
        setTimeout(function () { box.hidden = true; }, 6000);
    }
    function requireOwner() {
        if (isOwner()) return true;
        toast('共享母题由 studyadmin 维护，你可以查看并用它学习。');
        return false;
    }

    var ready = (async function () {
        try {
            var results = await Promise.all([request('/auth/config'), request('/auth/me')]);
            var config = results[0], me = results[1];
            state.enabled = config.enabled !== false;
            state.config = config;
            state.authenticated = !!me.authenticated;
            state.user = me.user || null;
            state.expires_at = me.expires_at;
            if (!state.enabled && !state.user) { state.user = {id: 'local', username: 'studyadmin', role: 'owner'}; state.authenticated = true; }
            if (isDemo) { state.user = {id: window.STUDY_DEMO.session_id, username: '游客', role: 'guest'}; state.authenticated = true; }
            if (!state.authenticated && !publicPage) redirectLogin();
        } catch (error) {
            if (error.status === 404) {
                state.enabled = false;
                state.authenticated = true;
                state.user = {id: 'local', username: 'studyadmin', role: 'owner'};
            } else if (isDemo) {
                state.authenticated = true;
                state.user = {id: window.STUDY_DEMO.session_id, username: '游客', role: 'guest'};
            } else if (!publicPage) { redirectLogin(); }
            state.error = error;
        }
        storageScope = state.enabled ? 'study_user:' + (state.user ? state.user.id : 'anonymous') + ':' : '';
        document.documentElement.dataset.studyRole = state.user ? state.user.role : 'anonymous';
        return state;
    })();

    window.StudyAuth = {ready: ready, state: state, request: request, isOwner: isOwner, requireOwner: requireOwner, toast: toast};
    if (!publicPage) window.fetch = function (input, init) {
        var url = new URL(input instanceof Request ? input.url : input, location.href);
        if (url.origin !== location.origin || url.pathname.indexOf('/auth/') === 0) return nativeFetch(input, init);
        return ready.then(function () { return nativeFetch(input, init); }).then(function (response) {
            if (response.status === 401 && state.enabled) {
                response.clone().json().then(function (body) {
                    if (!isDemo && ['authentication_required', 'session_expired', 'auth_required'].indexOf(body.error) >= 0) redirectLogin();
                }).catch(function () {});
            }
            return response;
        });
    };

    function applyPermissions() {
        if (isOwner()) return;
        document.querySelectorAll('[data-owner-only]').forEach(function (element) { element.hidden = true; });
        document.querySelectorAll('a[data-page="level-editor"]').forEach(function (element) { element.hidden = true; });
        if (/\/mother\.html$/.test(location.pathname)) {
            document.querySelectorAll('#motherEditForm input, #motherEditForm select, #motherEditForm textarea').forEach(function (element) { element.disabled = true; });
            document.querySelectorAll('#motherEditForm .form-actions, #motherEditForm .add-question-row, .q-remove').forEach(function (element) { element.hidden = true; });
        }
        document.querySelectorAll('.source-type-option[data-value="精选母题"]').forEach(function (element) { element.hidden = true; });
    }

    function mountAccountMenu() {
        var sidebar = document.querySelector('.sidebar');
        if (!sidebar || document.getElementById('auth-account')) return;
        var menu = document.createElement('div'); menu.id = 'auth-account'; menu.className = 'auth-account';
        var toggle = document.createElement('button'); toggle.className = 'auth-account-toggle'; toggle.type = 'button'; toggle.textContent = '👤'; toggle.setAttribute('aria-label', '账号菜单'); toggle.setAttribute('aria-expanded', 'false');
        var details = document.createElement('div'); details.className = 'auth-account-details';
        toggle.addEventListener('click', function () { var open = menu.classList.toggle('auth-menu-open'); toggle.setAttribute('aria-expanded', String(open)); });
        document.addEventListener('click', function (event) { if (!menu.contains(event.target)) { menu.classList.remove('auth-menu-open'); toggle.setAttribute('aria-expanded', 'false'); } });
        var name = document.createElement('strong'); name.textContent = state.user ? state.user.username : '未登录';
        var role = document.createElement('span'); role.textContent = isOwner() ? '主人账号' : (state.user && state.user.role === 'guest' ? '游客体验 · 2 小时' : '个人学习空间');
        var settings = document.createElement('a'); settings.href = '/settings.html'; settings.textContent = '账号与 API Key';
        var logout = document.createElement('button'); logout.type = 'button'; logout.textContent = state.user && state.user.role === 'guest' ? '登录 / 创建账号' : '退出 / 切换账号';
        logout.addEventListener('click', async function () {
            logout.disabled = true;
            try { await request('/auth/logout', 'POST', {}); location.replace('/login.html'); }
            catch (error) { toast(error.message); logout.disabled = false; }
        });
        details.append(name, role, settings, logout); menu.append(toggle, details); sidebar.appendChild(menu);
    }
    if (!publicPage) {
        var css = document.createElement('link'); css.rel = 'stylesheet'; css.href = '/auth.css?v=20261009a'; document.head.appendChild(css);
    }
    document.addEventListener('DOMContentLoaded', function () {
        ready.then(function () {
            mountAccountMenu(); applyPermissions();
            if (!isOwner()) {
                new MutationObserver(applyPermissions).observe(document.body, {childList: true, subtree: true});
                if (/\/mother\.html$/.test(location.pathname)) {
                    var note = document.createElement('p'); note.className = 'auth-readonly-note'; note.textContent = '共享母题 · 所有账号可查看，由 studyadmin 统一维护。';
                    document.querySelector('.mother-header').after(note);
                    var heading = document.querySelector('#motherEditForm').previousElementSibling;
                    if (heading) heading.textContent = '套路详情';
                }
                if (/\/level-editor\.html$/.test(location.pathname)) location.replace('/board.html');
            }
        });
    });
})();
