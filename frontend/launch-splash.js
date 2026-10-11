/* A short, skippable opening. Shared by the owner and visitor homepages. */
(function () {
    'use strict';
    var params = new URLSearchParams(location.search);
    var forced = params.get('launch') === '1';
    var seenKey = 'study_launch_seen_v3';
    if (forced) {
        params.delete('launch');
        try {
            history.replaceState(history.state, '', location.pathname +
                (params.toString() ? '?' + params.toString() : '') + location.hash);
        } catch (ignore) {}
    }
    try {
        if (!forced && sessionStorage.getItem(seenKey)) return;
        sessionStorage.setItem(seenKey, '1');
    } catch (ignore) {}
    var motion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');
    if (motion && motion.matches) return;

    var splash = document.createElement('section');
    splash.className = 'launch-splash';
    splash.setAttribute('role', 'dialog');
    splash.setAttribute('aria-modal', 'true');
    splash.setAttribute('aria-labelledby', 'launch-title');
    splash.setAttribute('tabindex', '-1');
    splash.innerHTML =
        '<header class="launch-topbar">' +
            '<span class="launch-brand"><span class="launch-brand-mark" aria-hidden="true">∑</span>成为数学高手</span>' +
            '<button class="launch-skip" type="button">跳过开场<span aria-hidden="true">↗</span></button>' +
        '</header>' +
        '<div class="launch-atmosphere" aria-hidden="true">' +
            '<span class="launch-formula launch-formula-one">f(x)</span>' +
            '<span class="launch-formula launch-formula-two">∞</span>' +
            '<span class="launch-formula launch-formula-three">x² + y²</span>' +
        '</div>' +
        '<div class="launch-composition">' +
            '<p class="launch-eyebrow"><span aria-hidden="true"></span>把热爱，写进每一步</p>' +
            '<h1 id="launch-title" class="launch-title">' +
                '<span class="launch-sr-only">数学，值得热爱。</span>' +
                '<img class="launch-lettering" src="/launch-lettering.svg?v=20261010e" width="800" height="420" alt="" aria-hidden="true">' +
            '</h1>' +
            '<div class="launch-caption"><p>从这一题，走向更多可能。</p>' +
                '<span>你的 AI 数学学习伴侣</span></div>' +
        '</div>' +
        '<footer class="launch-footer"><span>每一步，都算进步。</span>' +
            '<span class="launch-sequence" aria-hidden="true">01 <i></i> 开始探索</span></footer>' +
        '<div class="launch-timeline" aria-hidden="true"><span></span></div>';

    var previouslyFocused = document.activeElement;
    var suppressed = [];
    var closed = false;
    var removed = false;
    var timer;
    var removalTimer;
    var resolveFinished;
    var lifecycle = {
        active: true,
        finished: new Promise(function (resolve) { resolveFinished = resolve; })
    };
    window.StudyLaunchSplash = lifecycle;
    document.body.classList.add('launch-active');
    document.body.appendChild(splash);
    var skip = splash.querySelector('button');

    // The script runs before the homepage markup is parsed. Suppress background
    // controls after parsing and restore their original inert state on exit.
    function suppressBackground() {
        if (closed) return;
        Array.from(document.body.children).forEach(function (element) {
            if (element === splash || /^(SCRIPT|STYLE|LINK)$/.test(element.tagName)) return;
            if (suppressed.some(function (entry) { return entry.element === element; })) return;
            suppressed.push({ element: element, inert: element.inert });
            element.inert = true;
        });
    }
    function restoreBackground() {
        suppressed.forEach(function (entry) { entry.element.inert = entry.inert; });
        suppressed = [];
    }
    function remove() {
        if (removed) return;
        removed = true;
        clearTimeout(timer);
        clearTimeout(removalTimer);
        document.body.classList.remove('launch-active');
        restoreBackground();
        splash.remove();
        document.removeEventListener('DOMContentLoaded', suppressBackground);
        document.removeEventListener('keydown', onKeydown, true);
        document.removeEventListener('focusin', onFocus, true);
        window.removeEventListener('pagehide', onPagehide);
        if (motion && motion.removeEventListener) motion.removeEventListener('change', onMotionChange);
        lifecycle.active = false;
        resolveFinished();
        document.dispatchEvent(new CustomEvent('study:launch-finished'));
        if (document.activeElement === document.body && previouslyFocused &&
            previouslyFocused !== document.body && previouslyFocused.isConnected) {
            previouslyFocused.focus({ preventScroll: true });
        }
    }
    function close() {
        if (closed) return;
        closed = true;
        clearTimeout(timer);
        splash.classList.add('leaving');
        removalTimer = setTimeout(remove, 560);
    }
    function onKeydown(event) {
        if (event.key === 'Escape') { event.preventDefault(); close(); }
        if (event.key === 'Tab') { event.preventDefault(); skip.focus({ preventScroll: true }); }
    }
    function onFocus(event) {
        if (!closed && !splash.contains(event.target)) skip.focus({ preventScroll: true });
    }
    function onPagehide() { closed = true; remove(); }
    function onMotionChange(event) { if (event.matches) { closed = true; remove(); } }

    skip.addEventListener('click', close);
    document.addEventListener('keydown', onKeydown, true);
    document.addEventListener('focusin', onFocus, true);
    window.addEventListener('pagehide', onPagehide);
    if (motion && motion.addEventListener) motion.addEventListener('change', onMotionChange);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', suppressBackground);
    else suppressBackground();
    splash.focus({ preventScroll: true });
    timer = setTimeout(close, 2800);
})();
