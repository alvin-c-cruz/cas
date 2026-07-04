/* Shared search-select built on Choices.js.
 *
 * initSearchSelect(selectEl, options) → returns the Choices instance.
 *
 * options:
 *   choicesOptions : object   extra Choices config (merged over the defaults)
 *   addAction      : { value, label, onSelect }   optional pinned "add new…"
 *                    action kept at the top of the list and always reachable
 *
 * Behaviours (work for any picker that calls this):
 *   - Stable (label) ordering on open and on each search — this Choices build
 *     re-ranks search hits by fuzzy score, which is unintuitive for coded data.
 *   - Best-match highlight: the highlighted/auto-completed row is the first
 *     option (in label order) that STARTS WITH the typed text, else the first
 *     that CONTAINS it, else the first row. Uses Choices' own _highlightChoice
 *     so Enter/arrow keys stay in sync.
 *   - Inline autocomplete: fills the field with the target's value and selects
 *     the not-yet-typed remainder, so the next keystroke overwrites it.
 *     Skipped on backspace/delete and when the target doesn't start with the
 *     typed text.
 *   - addAction: pinned at the top; when the fuzzy filter would drop it, a
 *     clickable fallback is injected so it is always available.
 */

function _ssInsertAddOption(selectEl, value, label) {
    if (!selectEl || selectEl.querySelector('option[value="' + value + '"]')) return;
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = label;
    const placeholder = selectEl.options[0];
    if (placeholder && placeholder.nextSibling) {
        selectEl.insertBefore(opt, placeholder.nextSibling);
    } else {
        selectEl.appendChild(opt);
    }
}

function initSearchSelect(selectEl, options) {
    options = options || {};
    const add = options.addAction || null;            // { value, label, onSelect }
    const choicesOptions = options.choicesOptions || {};

    // Pin the add-action as the first <option> before Choices reads the select.
    if (add) _ssInsertAddOption(selectEl, add.value, add.label);

    // Capture DECODED labels (textContent) before `new Choices` consumes the
    // <select>'s options. Choices.js reads each <option>'s innerHTML as its
    // label, and Jinja autoescapes option text, so the raw innerHTML carries
    // entities (&amp; &lt; &gt; &#34; &#39;). With allowHTML:false Choices
    // renders that escaped string as plain text, so the entity shows
    // LITERALLY. Feeding Choices the decoded text (and letting it re-escape
    // once via allowHTML:false) fixes this while staying XSS-safe.
    const preset = Array.from(selectEl.options).map(o => ({
        value: o.value,
        label: o.textContent,          // decoded: raw & < > " '
        selected: o.selected,
        disabled: o.disabled,
        placeholder: o.value === '',
    }));

    const choices = new Choices(selectEl, Object.assign({
        searchEnabled: true,
        itemSelectText: '',
        shouldSort: false,
        allowHTML: false,
    }, choicesOptions));

    // Replace Choices' innerHTML-derived (still-escaped) choices with the
    // decoded set captured above. `selected`/`placeholder` flags are carried
    // through so pre-selected values (edit forms) and the empty-value
    // placeholder (create forms) keep working.
    choices.setChoices(preset, 'value', 'label', true);

    const container = selectEl.closest('.choices');
    if (!container) return choices;

    const input = container.querySelector('input.choices__input--cloned')
               || container.querySelector('input.choices__input');

    // Track deletions so backspace/delete don't re-complete the field.
    let isDeleting = false;
    if (input) {
        input.addEventListener('keydown', function (e) {
            isDeleting = (e.key === 'Backspace' || e.key === 'Delete');
        });
    }

    function dropdownList() {
        return container.querySelector('.choices__list--dropdown .choices__list')
            || container.querySelector('.choices__list--dropdown');
    }

    function realOptions(list) {
        return Array.from(list.querySelectorAll('.choices__item--selectable')).filter(el => {
            const v = el.getAttribute('data-value');
            return v && v !== '' && (!add || v !== add.value);
        });
    }

    // Keep the add-action reachable even when the fuzzy filter drops it
    // (e.g. a query that matches nothing — exactly when you want to add one).
    function ensureAddAction(list) {
        if (!add || !list) return;
        const clone = list.querySelector('.search-select-add');
        if (list.querySelector('[data-value="' + add.value + '"]')) {
            if (clone) clone.remove();            // native present → drop stale clone
            return;
        }
        if (clone) return;                        // fallback already present
        const s = document.createElement('div');
        s.className = 'choices__item choices__item--choice choices__item--selectable search-select-add';
        s.setAttribute('role', 'option');
        s.textContent = add.label;
        s.addEventListener('mousedown', function (e) {
            e.preventDefault();                   // keep focus / stop Choices selecting
            e.stopPropagation();
            if (typeof choices.hideDropdown === 'function') choices.hideDropdown();
            if (typeof add.onSelect === 'function') add.onSelect();
        });
        s.addEventListener('mouseenter', function () { s.classList.add('is-highlighted'); });
        s.addEventListener('mouseleave', function () { s.classList.remove('is-highlighted'); });
        list.insertBefore(s, list.firstChild);
    }

    function reorderByLabel(list) {
        const opts = realOptions(list);
        if (opts.length > 1) {
            opts.sort((a, b) =>
                a.textContent.trim().localeCompare(b.textContent.trim(), undefined, { numeric: true }));
            opts.forEach(el => list.appendChild(el));
        }
        return opts;
    }

    // Best match for the query: prefix match first, then substring, then first.
    function pickTarget(opts, query) {
        if (!query) return opts[0];
        const q = query.toLowerCase();
        return opts.find(el => el.textContent.trim().toLowerCase().startsWith(q))
            || opts.find(el => el.textContent.trim().toLowerCase().indexOf(q) !== -1)
            || opts[0];
    }

    // Bold the matched run of `query` inside the option's label. Rebuilt with
    // text nodes + <strong> (no innerHTML), so it stays XSS-safe.
    function boldMatch(el, query) {
        if (!query) return;
        const text = el.textContent;
        const idx = text.toLowerCase().indexOf(query.toLowerCase());
        if (idx < 0) return;
        const strong = document.createElement('strong');
        strong.textContent = text.slice(idx, idx + query.length);
        el.textContent = '';
        if (idx > 0) el.appendChild(document.createTextNode(text.slice(0, idx)));
        el.appendChild(strong);
        const tail = text.slice(idx + query.length);
        if (tail) el.appendChild(document.createTextNode(tail));
    }

    // Drop everything except the add-action and show a single notice.
    function showNoResults(list) {
        Array.from(list.children).forEach(el => {
            const isAdd = el.classList.contains('search-select-add')
                || (add && el.getAttribute('data-value') === add.value);
            if (!isAdd) el.remove();
        });
        const notice = document.createElement('div');
        notice.className = 'choices__item search-select-noresults';
        notice.textContent = 'No results found';
        list.appendChild(notice);
    }

    selectEl.addEventListener('search', function () {
        // Defer until Choices has rendered the filtered list for this keystroke.
        requestAnimationFrame(function () {
            const list = dropdownList();
            if (!list) return;

            // The user's typed text = everything before the selection. After an
            // inline autocomplete the field holds "typed + completion(selected)",
            // so reading the whole value would mistake the completion for input.
            const typed = input ? input.value.slice(0, input.selectionStart) : '';
            const query = typed.trim();
            ensureAddAction(list);

            // Filter to substring matches of the ACTUAL characters typed — this
            // Choices build's fuzzy search is too loose (e.g. "v002" matches all).
            if (query) {
                const q = query.toLowerCase();
                realOptions(list).forEach(el => {
                    if (el.textContent.trim().toLowerCase().indexOf(q) === -1) el.remove();
                });
            }

            const opts = reorderByLabel(list);

            if (query && opts.length < 1) {
                showNoResults(list);   // keeps the add-action, single notice
                return;
            }
            if (opts.length < 1) return;

            if (query) opts.forEach(el => boldMatch(el, query));

            const target = pickTarget(opts, query);
            if (target && typeof choices._highlightChoice === 'function') {
                choices._highlightChoice(target);
            }

            if (input && !isDeleting && target) {
                const label = target.textContent.trim();
                if (typed && label.length > typed.length &&
                    label.toLowerCase().startsWith(typed.toLowerCase())) {
                    input.value = typed + label.slice(typed.length);
                    try { input.setSelectionRange(typed.length, label.length); } catch (e) { /* noop */ }
                }
            }
        });
    });

    // On open (no query yet), keep the list in label order so freshly-added
    // entries land in their sorted position without a page reload.
    selectEl.addEventListener('showDropdown', function () {
        requestAnimationFrame(function () {
            const list = dropdownList();
            if (!list) return;
            ensureAddAction(list);
            reorderByLabel(list);
        });
    });

    // Selecting the add-action runs its handler and restores the prior value.
    if (add) {
        let lastValue = (selectEl.value && selectEl.value !== add.value) ? selectEl.value : '';
        selectEl.addEventListener('change', function () {
            if (selectEl.value === add.value) {
                choices.setChoiceByValue(lastValue || '');
                if (typeof add.onSelect === 'function') add.onSelect();
            } else {
                lastValue = selectEl.value;
            }
        });
    }

    return choices;
}
