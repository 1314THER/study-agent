(function () {
    var params = new URLSearchParams(location.search);
    if (params.get('launch') !== '1') return;
    params.delete('launch');
    history.replaceState(null, '', location.pathname + (params.toString() ? '?' + params.toString() : '') + location.hash);
    var splash = document.createElement('div');
    splash.className = 'launch-splash';
    splash.innerHTML = '<div class="launch-mark">∑</div><h1>学习教练台</h1><p>每一步，都算进步。</p><button type="button">进入首页 →</button>';
    document.body.appendChild(splash);
    function close() { splash.classList.add('leaving'); setTimeout(function () { splash.remove(); }, 400); }
    splash.querySelector('button').addEventListener('click', close);
    setTimeout(close, matchMedia('(prefers-reduced-motion: reduce)').matches ? 250 : 1400);
})();
