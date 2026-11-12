(() => {
  const menuButton = document.querySelector('.menu-toggle');
  const nav = document.querySelector('#primary-nav');
  const navLinks = [...document.querySelectorAll('.primary-nav a')];
  const progressBar = document.querySelector('#reading-progress-bar');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  if (menuButton && nav) {
    menuButton.addEventListener('click', () => {
      const open = menuButton.getAttribute('aria-expanded') !== 'true';
      menuButton.setAttribute('aria-expanded', String(open));
      nav.classList.toggle('is-open', open);
      menuButton.querySelector('.sr-only').textContent = open ? '关闭目录' : '打开目录';
    });
    navLinks.forEach((link) => link.addEventListener('click', () => {
      menuButton.setAttribute('aria-expanded', 'false');
      nav.classList.remove('is-open');
      menuButton.querySelector('.sr-only').textContent = '打开目录';
    }));
  }

  const updateProgress = () => {
    if (!progressBar) return;
    const pageHeight = document.documentElement.scrollHeight - window.innerHeight;
    const progress = pageHeight > 0 ? Math.min(100, Math.max(0, (window.scrollY / pageHeight) * 100)) : 0;
    progressBar.style.width = `${progress}%`;
  };
  window.addEventListener('scroll', updateProgress, { passive: true });
  window.addEventListener('resize', updateProgress);
  updateProgress();

  const observedSections = navLinks
    .map((link) => document.querySelector(link.getAttribute('href')))
    .filter(Boolean);
  if ('IntersectionObserver' in window && observedSections.length) {
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      navLinks.forEach((link) => {
        const active = link.getAttribute('href') === `#${visible.target.id}`;
        if (active) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
        link.classList.toggle('is-active', active);
      });
    }, { rootMargin: '-18% 0px -68% 0px', threshold: [0, .15, .35, .6] });
    observedSections.forEach((section) => observer.observe(section));
  }

  const scenarios = {
    evidence: {
      src: '/wenxia-demo/assets/scenario-evidence.svg',
      href: '/wenxia-demo/assets/scenario-evidence.svg',
      title: '场景时序图上半部分：学生提交题目和作答，Agent 保存原始材料，CLEAN 保真识别，读取 DB3 与 DB2 历史，RAG1 检索闭区间最值的教学依据，GRADER 生成批改提案并经服务提交，然后 TUTOR 给出限制参考内容的一级提示。',
      caption: '图 2a　原图、识别、作答修订、双路检索、GradeDraft、正式评分与 TUTOR 提示。',
      tab: 'scenario-tab-evidence'
    },
    teaching: {
      src: '/wenxia-demo/assets/scenario-teaching.svg',
      href: '/wenxia-demo/assets/scenario-teaching.svg',
      title: '场景时序图下半部分：提示展示后写入 HintExposed，学生提示后订正保存为辅助作答，正式事件触发 TA 取证和 LLM WikiPatch，服务核验 base_revision 并更新 DB3，之后排除已暴露题族、规划无提示新题验证。',
      caption: '图 2b　提示暴露、辅助订正、事件消费、学情修订、排除已暴露题与独立验证。',
      tab: 'scenario-tab-teaching'
    }
  };
  const scenarioImage = document.querySelector('#scenario-diagram-image');
  const scenarioOpen = document.querySelector('#scenario-open');
  const scenarioCaption = document.querySelector('#scenario-caption');
  const scenarioPanel = document.querySelector('#scenario-panel');
  document.querySelectorAll('[data-scenario]').forEach((button) => {
    button.addEventListener('click', () => {
      const scenario = scenarios[button.dataset.scenario];
      if (!scenario || !scenarioImage) return;
      document.querySelectorAll('[data-scenario]').forEach((tab) => {
        const selected = tab === button;
        tab.setAttribute('aria-selected', String(selected));
        tab.tabIndex = selected ? 0 : -1;
      });
      scenarioImage.src = scenario.src;
      scenarioImage.alt = scenario.title;
      scenarioOpen.href = scenario.href;
      scenarioPanel.setAttribute('aria-labelledby', scenario.tab);
      scenarioCaption.textContent = scenario.caption;
    });
    button.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const tabs = [...document.querySelectorAll('[data-scenario]')];
      const next = tabs[(tabs.indexOf(button) + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      next.focus();
      next.click();
    });
  });

  const modelNotes = {
    '4B': {
      kicker: '资源下限档',
      title: '4B · 低资源能力边界',
      copy: '测低资源下的工具遵循、证据使用、结构化提案和有限提示。通过数据库与确定性服务分担记忆、筛选、计算和校验；对不能稳定完成的任务明确转复核，不把模型规模本身等同于可部署性。'
    },
    '9B': {
      kicker: '主线模型档',
      title: '9B · 系统核心评测档',
      copy: '优先回答：在三库、Agent Loop 和业务 LoRA 协同后，9B 能否覆盖已定义的解题、批改、提示、状态维护和教学协作任务；逐类报告失败，不以单一均分掩盖短板。'
    },
    '27B': {
      kicker: '高能力对照档',
      title: '27B · 质量上限与复杂任务',
      copy: '在相同数据、工具和任务中观察更大模型对开放式诊断、复杂解法与长上下文任务的提升，再核算硬件、时延与维护成本，界定哪些任务值得提升到这一档。'
    }
  };
  const modelFocus = document.querySelector('#model-focus');
  const modelTitle = document.querySelector('#model-focus-title');
  const modelCopy = document.querySelector('#model-focus-copy');
  const modelKicker = modelFocus?.querySelector('.focus-kicker');
  document.querySelectorAll('[data-model]').forEach((button) => {
    button.addEventListener('click', () => {
      const note = modelNotes[button.dataset.model];
      if (!note) return;
      document.querySelectorAll('[data-model]').forEach((option) => {
        const selected = option === button;
        option.classList.toggle('is-selected', selected);
        option.setAttribute('aria-pressed', String(selected));
      });
      modelKicker.textContent = note.kicker;
      modelTitle.textContent = note.title;
      modelCopy.textContent = note.copy;
    });
  });

  if (reduceMotion) document.documentElement.classList.add('reduce-motion');
})();
