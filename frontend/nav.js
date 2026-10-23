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

    // Every page uses the same menu. Reuse existing links to preserve badges
    // and page-specific URLs, but fill missing entries and stabilize the order.
    var navigation = [
        ['home','home.html','首页','🏠'],
        ['multimodal','multimodal.html','多模态解答','📎'],
        ['teach','teach.html','老师手把手教你做题','📖'],
        ['exam','exam.html','组卷','📝'],
        ['exam-analysis','exam-analysis.html','整卷分析','📊'],
        ['student-analysis','student-analysis.html','学生分析','📈'],
        ['history','history.html','个人题库','📋'],
        ['mother','mother.html','母题看板','🧠'],
        ['question-pool','question-pool.html','原题池','🗂️',true],
        ['routine-review','routine-review.html','套路审核','📝',true],
        ['routine-graph','routine-graph.html','套路图谱','🕸️',true],
        ['curriculum-wiki','curriculum-wiki.html','数学课时库','📚',true],
        ['loop','loop.html','套路循环','🔄'],
        ['calendar','calendar.html','巩固日历','📅'],
        ['board','board.html','闯关','🗺️'],
        ['level-editor','level-editor.html','关卡编辑','🧩',true],
        ['solve','index.html','单题解答','🔍'],
        ['grade','grade.html','AI 改卷','✅'],
        ['settings','settings.html','系统设置','⚙️']
    ];
    function syncNavigation(permissionsReady) {
        var nav = document.querySelector('.sidebar > nav');
        if (!nav) return;
        var current = location.pathname.split('/').pop() || 'home.html';
        navigation.forEach(function(entry) {
            var page=entry[0], link=nav.querySelector('a[data-page="'+page+'"]');
            if (!link) {
                link=document.createElement('a'); link.href=entry[1];
                link.className='nav-item'; link.setAttribute('data-page',page);
                var icon=document.createElement('span'); icon.className='nav-icon'; icon.textContent=entry[3];
                var label=document.createElement('span'); label.className='nav-label'; label.textContent=entry[2];
                link.append(icon,label);
            }
            link.title=entry[2];
            if(entry[4]) link.setAttribute('data-owner-only','');
            if(permissionsReady && entry[4]) link.hidden=!window.StudyAuth.isOwner();
            link.classList.toggle('active',current===entry[1]);
            if(current===entry[1]) link.setAttribute('aria-current','page');
            else link.removeAttribute('aria-current');
            nav.appendChild(link);
        });
        var active=nav.querySelector('a.active');
        if(active && active.offsetTop>nav.clientHeight) nav.scrollTop=Math.max(0,active.offsetTop-nav.clientHeight/2);
        markDemoNavigation(nav);
    }
    function markDemoNavigation(nav) {
        if (!window.STUDY_DEMO) return;
        nav.querySelectorAll('a[href]').forEach(function(a) {
            if (!/(?:grade|mother|loop|level-editor)\.html(?:[?#]|$)/.test(a.getAttribute('href'))) return;
            a.title='暂未开发完成';
            var label=a.querySelector('.nav-label');
            if(label && !label.textContent.includes('暂未完成')) label.textContent+=' · 暂未完成';
        });
    }

    function loadAgent() {
        if (window.STUDY_DISABLE_AGENT) return;
        if (window.AgentGlobal || document.getElementById('agentScript')) return;
        var s = document.createElement('script');
        s.id = 'agentScript';
        s.src = 'agent.js?v=20261004a';
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
        syncNavigation(false);
        if (window.StudyAuth) window.StudyAuth.ready.then(function () { syncNavigation(true); });
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
