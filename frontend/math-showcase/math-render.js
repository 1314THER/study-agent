(() => {
  'use strict';
  const pattern = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)/g;
  const ignored = 'script, noscript, style, textarea, pre, code, option, .katex, .math-rendered';

  window.renderMathInElement = function renderMathInElement(root) {
    if (!root || !window.katex) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        return node.data && !node.parentElement?.closest(ignored)
          ? NodeFilter.FILTER_ACCEPT
          : NodeFilter.FILTER_REJECT;
      },
    });
    const textNodes = [];
    while (walker.nextNode()) textNodes.push(walker.currentNode);

    for (const node of textNodes) {
      const text = node.data;
      pattern.lastIndex = 0;
      let match;
      let last = 0;
      let found = false;
      const fragment = document.createDocumentFragment();
      while ((match = pattern.exec(text))) {
        const expression = match[1] ?? match[2] ?? match[3] ?? match[4];
        if (!expression.trim()) continue;
        found = true;
        if (match.index > last) fragment.append(document.createTextNode(text.slice(last, match.index)));
        const display = match[1] !== undefined || match[3] !== undefined;
        const rendered = document.createElement(display ? 'span' : 'span');
        rendered.className = 'math-rendered';
        if (display) rendered.classList.add('math-rendered-display');
        try {
          window.katex.render(expression, rendered, { displayMode: display, throwOnError: false, strict: 'ignore' });
        } catch {
          rendered.textContent = match[0];
        }
        fragment.append(rendered);
        last = pattern.lastIndex;
      }
      if (!found) continue;
      if (last < text.length) fragment.append(document.createTextNode(text.slice(last)));
      node.parentNode?.replaceChild(fragment, node);
    }
  };
})();
