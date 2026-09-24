/* 题目搜索选择器：输入关键词搜题库，点选后把题目 ID 写进隐藏字段。 */
(function () {
    var timers = {};

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function targetId(input) {
        return input.getAttribute('data-target-id') || '';
    }

    function resultsId(input) {
        return input.getAttribute('data-results-id') || '';
    }

    function clearHidden(input) {
        var hid = document.getElementById(targetId(input));
        if (hid) hid.value = '';
    }

    function schedule(input) {
        clearHidden(input);
        var key = input.id || targetId(input);
        clearTimeout(timers[key]);
        var q = input.value.trim();
        var box = document.getElementById(resultsId(input));
        if (box) box.innerHTML = '';
        if (!q) return;
        timers[key] = setTimeout(function () {
            search(input, q, box);
        }, 220);
    }

    async function search(input, q, box) {
        if (!box) return;
        try {
            var r = await fetch('/questions/search?q=' + encodeURIComponent(q) + '&limit=8&page_size=8');
            var data = await r.json();
            var list = (data && data.data) || data || [];
            if (!list.length) {
                box.innerHTML = '<div class="question-search-empty">没有匹配的题目</div>';
                return;
            }
            var html = '';
            for (var i = 0; i < list.length; i++) {
                var it = list[i];
                var preview = String(it.content || '').replace(/\s+/g, ' ').slice(0, 70);
                var meta = [it.question_type || '', it.category_level1 || ''].filter(Boolean).join(' · ');
                html += '<div class="question-search-item" data-id="' + it.id +
                    '" data-target="' + targetId(input) +
                    '" data-search="' + (input.id || '') + '">' +
                    '<span class="question-search-item-id">#' + it.id + '</span>' +
                    '<span class="question-search-item-preview">' + esc(preview) + '</span>' +
                    (meta ? '<span class="question-search-item-meta">' + esc(meta) + '</span>' : '') +
                    '</div>';
            }
            box.innerHTML = html;
        } catch (e) {
            box.innerHTML = '<div class="question-search-empty">搜索失败</div>';
        }
    }

    function pick(item) {
        var hid = document.getElementById(item.getAttribute('data-target'));
        if (hid) hid.value = item.getAttribute('data-id');
        var input = document.getElementById(item.getAttribute('data-search'));
        if (!input) return;
        var previewEl = item.querySelector('.question-search-item-preview');
        var preview = previewEl ? previewEl.textContent : '';
        input.value = '#' + item.getAttribute('data-id') + ' ' + preview;
        var box = document.getElementById(resultsId(input));
        if (box) box.innerHTML = '';
    }

    document.addEventListener('input', function (e) {
        if (e.target && e.target.classList && e.target.classList.contains('question-search-input')) {
            schedule(e.target);
        }
    });
    document.addEventListener('click', function (e) {
        var item = e.target && e.target.closest ? e.target.closest('.question-search-item') : null;
        if (item) pick(item);
    });
})();
