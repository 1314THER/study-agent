/*
 * 全局导航：窄屏时把侧栏收成抽屉，支持按钮/遮罩/Esc 关闭。
 */
(function () {
    document.documentElement.classList.add('nav-init');

    function toggleMobileNav() {
        document.body.classList.toggle('mobile-nav-open');
    }

    function closeMobileNav() {
        document.body.classList.remove('mobile-nav-open');
    }

    function toggleNavExpand() {
        var currentlyExpanded = document.body.classList.contains('nav-expanded');
        if (!currentlyExpanded && !document.body.classList.contains('nav-collapsed')) {
            currentlyExpanded = window.innerWidth > 1800;
        }
        var expanded = !currentlyExpanded;
        document.body.classList.toggle('nav-expanded', expanded);
        document.body.classList.toggle('nav-collapsed', !expanded);
        try {
            localStorage.setItem('nav_expanded', expanded ? '1' : '0');
        } catch (e) {}
    }

    window.toggleMobileNav = toggleMobileNav;
    window.toggleNavExpand = toggleNavExpand;

    function injectHomeNav() {
        var nav = document.querySelector('nav');
        if (!nav || document.querySelector('nav a[data-page="home"]')) return;
        var a = document.createElement('a');
        a.href = 'home.html';
        a.className = 'nav-item';
        a.setAttribute('data-page', 'home');
        a.title = '首页';
        a.innerHTML = '<span class="nav-icon">🏠</span><span class="nav-label">首页</span>';
        nav.insertBefore(a, nav.firstChild);
    }

    function loadAgent() {
        if (window.AgentGlobal || document.getElementById('agentScript')) return;
        var s = document.createElement('script');
        s.id = 'agentScript';
        s.src = 'agent.js?v=20260809g';
        document.head.appendChild(s);
    }

    document.addEventListener('DOMContentLoaded', function () {
        try {
            var saved = localStorage.getItem('nav_expanded');
            if (saved === '1') {
                document.body.classList.add('nav-expanded');
                document.body.classList.remove('nav-collapsed');
            } else if (saved === '0') {
                document.body.classList.add('nav-collapsed');
                document.body.classList.remove('nav-expanded');
            }
        } catch (e) {}
        injectHomeNav();
        loadAgent();
        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                document.documentElement.classList.remove('nav-init');
            });
        });
    });

    document.addEventListener('click', function (e) {
        if (e.target.closest('.sidebar') || e.target.closest('.mobile-nav-toggle')) return;
        closeMobileNav();
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeMobileNav();
    });

    loadAgent();
})();
