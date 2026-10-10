(function () {
    'use strict';
    var auth = window.StudyAuth;
    var registrationEnabled = false;
    var resendUntil = 0;
    var resendTimer;
    var message = document.getElementById('login-message');
    function showMessage(text, error) {
        message.hidden = false;
        message.className = 'login-helper auth-message ' + (error ? 'error' : 'success');
        message.textContent = text;
    }
    function showPanel(type) {
        document.getElementById('login-options').hidden = !!type;
        document.getElementById('welcome-heading').hidden = !!type;
        document.getElementById('login-panel').hidden = type !== 'login';
        document.getElementById('register-panel').hidden = type !== 'register';
        message.hidden = true;
        if (type) document.querySelector('#' + type + '-form input').focus();
    }
    document.getElementById('open-register').addEventListener('click', function () { showPanel('register'); });
    document.getElementById('open-login').addEventListener('click', function () { showPanel('login'); });
    document.querySelectorAll('[data-back]').forEach(function (button) { button.addEventListener('click', function () { showPanel(''); }); });
    function fields(form) { return Object.fromEntries(new FormData(form)); }
    function busy(form, value) {
        form.querySelector('button[type="submit"]').disabled = value;
        form.setAttribute('aria-busy', value ? 'true' : 'false');
    }
    function enter() { location.replace('/home.html?launch=1'); }

    document.getElementById('guest-login').addEventListener('click', async function () {
        var button = this; button.disabled = true; button.textContent = '正在进入…';
        try { await auth.request('/auth/guest', 'POST', {}); enter(); }
        catch (error) { showMessage(error.message, true); button.disabled = false; button.textContent = '开始体验 →'; }
    });
    document.getElementById('login-form').addEventListener('submit', async function (event) {
        event.preventDefault(); var form = this; busy(form, true); message.hidden = true;
        var data = fields(form);
        try { await auth.request('/auth/login', 'POST', {login: data.login.trim(), password: data.password}); form.reset(); enter(); }
        catch (error) { showMessage(error.message, true); busy(form, false); }
    });
    function updateResend() {
        var seconds = Math.max(0, Math.ceil((resendUntil - Date.now()) / 1000));
        var button = document.getElementById('send-code');
        button.textContent = seconds ? seconds + ' 秒后重发' : '发送验证码';
        button.disabled = !registrationEnabled || !!seconds;
        if (!seconds) clearInterval(resendTimer);
    }
    document.getElementById('send-code').addEventListener('click', async function () {
        var email = document.querySelector('#register-form [name="email"]');
        if (!email.reportValidity()) return;
        this.disabled = true; this.textContent = '正在发送…';
        try {
            var result = await auth.request('/auth/email-code', 'POST', {email: email.value.trim(), purpose: 'register'});
            showMessage(result.message || '如果该邮箱可用于注册，验证码将在几分钟内送达。请检查收件箱与垃圾邮件。');
            resendUntil = Date.now() + 60000; updateResend(); resendTimer = setInterval(updateResend, 1000);
        } catch (error) { showMessage(error.message, true); updateResend(); }
    });
    document.getElementById('register-form').addEventListener('submit', async function (event) {
        event.preventDefault(); var form = this; var data = fields(form);
        if (!registrationEnabled) { showMessage('管理员尚未启用邮箱注册，请先使用游客体验。', true); return; }
        if (data.password !== data.confirm_password) { showMessage('两次输入的密码不一致。', true); return; }
        if (/\s/.test(data.api_key.trim())) { showMessage('API Key 不能包含空格或换行。', true); return; }
        busy(form, true); message.hidden = true;
        try {
            await auth.request('/auth/register', 'POST', {username: data.username.trim(), email: data.email.trim(), code: data.code.trim(), password: data.password, api_key: data.api_key.trim()});
            form.reset(); enter();
        } catch (error) { showMessage(error.message, true); busy(form, false); }
    });

    auth.ready.then(function (state) {
        var config = state.config || {};
        registrationEnabled = !!config.registration_enabled;
        var registerForm = document.getElementById('register-form');
        registerForm.querySelectorAll('button').forEach(function (button) { button.disabled = !registrationEnabled; });
        if (!registrationEnabled) {
            var note = document.getElementById('registration-note'); note.hidden = false;
            note.textContent = '管理员尚未启用邮箱验证码服务。现在可以使用游客体验；已注册的账号可以正常登录。';
        }
        if (state.error && state.error.status !== 404) showMessage('暂时无法连接账号服务，请稍后重试。', true);
        if (state.authenticated && state.enabled && state.user && state.user.role !== 'guest') {
            showMessage('你已登录为 ' + state.user.username + '。');
            var link = document.createElement('a'); link.href = '/home.html'; link.textContent = '继续学习 →'; link.style.marginLeft = '12px'; message.appendChild(link);
        }
    });
})();
