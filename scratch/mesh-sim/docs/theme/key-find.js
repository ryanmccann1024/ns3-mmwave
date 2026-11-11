/* Type-to-filter for the key cards on the file reference pages (files/*.md).
 *
 * The page holds one .ms-find box (data-noun names what is counted, e.g.
 * "column") and any number of .ms-keys lists of .ms-key cards. Typing hides every card that does not contain the text,
 * and hides everything else on the page except the headings of sections that
 * still have a match. Clearing the box restores the page. "/" focuses the box.
 */
(function () {
    function init() {
        var box = document.querySelector('.ms-find input');
        var block = document.querySelector('div.textblock');
        if (!box || !block) {
            return;
        }
        var count = document.querySelector('.ms-find-count');
        var finder = box.closest('.ms-find');
        var noun = finder.getAttribute('data-noun') || 'key';

        /* Pair each heading with the key lists that follow it. */
        var items = [];
        var heading = null;
        Array.prototype.forEach.call(block.children, function (el) {
            if (/^H[1-4]$/.test(el.tagName)) {
                heading = { el: el, lists: [] };
                items.push(heading);
            } else if (el.classList.contains('ms-keys')) {
                if (heading) {
                    heading.lists.push(el);
                }
                items.push({ list: el });
            } else if (!el.contains(finder)) {
                items.push({ other: el });
            }
        });

        function apply() {
            var q = box.value.trim().toLowerCase();
            var hits = 0;
            items.forEach(function (it) {
                if (it.list) {
                    var any = false;
                    it.list.querySelectorAll('.ms-key:not(.ms-key-head)').forEach(function (card) {
                        var show = !q || card.textContent.toLowerCase().indexOf(q) !== -1;
                        card.style.display = show ? '' : 'none';
                        if (show) {
                            any = true;
                            hits += 1;
                        }
                    });
                    it.list.style.display = any ? '' : 'none';
                }
            });
            items.forEach(function (it) {
                if (it.other) {
                    it.other.style.display = q ? 'none' : '';
                } else if (it.el) {
                    var keep = !q || it.lists.some(function (l) { return l.style.display !== 'none'; });
                    it.el.style.display = keep ? '' : 'none';
                }
            });
            if (count) {
                count.textContent = !q ? '' : hits + ' ' + noun + (hits === 1 ? '' : 's');
            }
        }

        box.addEventListener('input', apply);
        box.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                box.value = '';
                apply();
            }
        });
        document.addEventListener('keydown', function (e) {
            var t = e.target.tagName;
            if (e.key === '/' && t !== 'INPUT' && t !== 'TEXTAREA') {
                e.preventDefault();
                box.focus();
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
