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

    function injectQuestionPoolNav() {
        if (!window.StudyAuth || !window.StudyAuth.isOwner()) return;
        var nav = document.querySelector('nav');
        if (!nav || nav.querySelector('a[data-page="question-pool"]')) return;
        var link = document.createElement('a');
        link.href = 'question-pool.html';
        link.className = 'nav-item';
        link.setAttribute('data-page', 'question-pool');
        link.setAttribute('data-owner-only', '');
        link.title = '原题池';
        var icon = document.createElement('span'); icon.className = 'nav-icon'; icon.textContent = '🗂️';
        var label = document.createElement('span'); label.className = 'nav-label'; label.textContent = '原题池';
        link.append(icon, label);
        var mother = nav.querySelector('a[data-page="mother"]');
        if (mother) mother.after(link); else nav.appendChild(link);
    }

    function loadAgent() {
        if (window.AgentGlobal || document.getElementById('agentScript')) return;
        var s = document.createElement('script');
        s.id = 'agentScript';
        s.src = 'agent.js?v=20261004a';
        document.head.appendChild(s);
    }

    function injectRoutineReviewNav() {
        if (!window.StudyAuth || !window.StudyAuth.isOwner()) return;
        var nav = document.querySelector('nav');
        if (!nav || nav.querySelector('a[data-page="routine-review"]')) return;
        var link = document.createElement('a');
        link.href = 'routine-review.html';
        link.className = 'nav-item';
        link.setAttribute('data-page', 'routine-review');
        link.setAttribute('data-owner-only', '');
        link.title = '套路审核';
        var icon = document.createElement('span'); icon.className = 'nav-icon'; icon.textContent = '📝';
        var label = document.createElement('span'); label.className = 'nav-label'; label.textContent = '套路审核';
        link.append(icon, label);
        var pool = nav.querySelector('a[data-page="question-pool"]');
        if (pool) pool.after(link); else nav.appendChild(link);
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
        if (window.StudyAuth) window.StudyAuth.ready.then(function () { injectQuestionPoolNav(); injectRoutineReviewNav(); });
        if (window.STUDY_DEMO) {
            document.querySelectorAll('a[href]').forEach(function(a) {
                if (!/(?:grade|mother|loop|level-editor)\.html(?:[?#]|$)/.test(a.getAttribute('href'))) return;
                a.title = '暂未开发完成';
                var label=a.querySelector('.nav-label');
                if(label && !label.textContent.includes('暂未完成')) label.textContent += ' · 暂未完成';
            });
        }
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
