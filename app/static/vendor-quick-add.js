/* Inline "+ Add Vendor" wiring. Call initVendorQuickAdd once per page.
   opts = { choices, selectEl }  where `choices` is the page's Choices instance
   for the vendor select and `selectEl` is that <select> element.
   Requires Choices to be loaded and #vendorQuickAddOverlay to be present. */
const VENDOR_ADD_SENTINEL = '__add_vendor__';

/* Insert the "➕ Add Vendor…" option at the TOP of the vendor <select>
   (right after the empty placeholder) BEFORE Choices.js is initialized, so it
   leads the dropdown list rather than trailing the vendor entries. */
function addVendorSentinelOption(selectEl) {
    if (!selectEl || selectEl.querySelector('option[value="' + VENDOR_ADD_SENTINEL + '"]')) return;
    const opt = document.createElement('option');
    opt.value = VENDOR_ADD_SENTINEL;
    opt.textContent = '➕ Add Vendor…';
    const placeholder = selectEl.options[0];
    if (placeholder && placeholder.nextSibling) {
        selectEl.insertBefore(opt, placeholder.nextSibling);
    } else if (placeholder) {
        selectEl.appendChild(opt);
    } else {
        selectEl.appendChild(opt);
    }
}

/* Make the vendor picker behave like a predictable typeahead: this Choices
   build re-ranks search results by fuzzy score, which is unintuitive for coded
   records. On each search/open, re-order the options back into the list's own
   (code) order, keep "Add Vendor" pinned at the top even when the fuzzy filter
   would drop it, highlight the first match via Choices' own mechanism (so
   Enter/arrow keys stay in sync), and inline-autocomplete the field. */
function enhanceVendorTypeahead(choices, selectEl, openModal) {
    const container = selectEl.closest('.choices');
    if (!container) return;
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

    function vendorOptions(list) {
        return Array.from(list.querySelectorAll('.choices__item--selectable')).filter(el => {
            const v = el.getAttribute('data-value');
            return v && v !== '' && v !== VENDOR_ADD_SENTINEL;
        });
    }

    // Keep "Add Vendor" reachable even when the fuzzy filter would drop the
    // native option (e.g. a query that matches no vendor — exactly when you
    // want to add one). When the native option is gone, inject a clickable
    // fallback at the top of the dropdown.
    function ensureSentinel(list) {
        if (!list) return;
        const clone = list.querySelector('.vendor-add-sentinel');
        if (list.querySelector('[data-value="' + VENDOR_ADD_SENTINEL + '"]')) {
            if (clone) clone.remove();   // native present → drop any stale clone
            return;
        }
        if (clone) return;               // our fallback is already present
        const s = document.createElement('div');
        s.className = 'choices__item choices__item--choice choices__item--selectable vendor-add-sentinel';
        s.setAttribute('role', 'option');
        s.textContent = '➕ Add Vendor…';
        s.addEventListener('mousedown', function (e) {
            e.preventDefault();          // keep focus / stop Choices selecting
            e.stopPropagation();
            if (typeof choices.hideDropdown === 'function') choices.hideDropdown();
            openModal();
        });
        s.addEventListener('mouseenter', function () { s.classList.add('is-highlighted'); });
        s.addEventListener('mouseleave', function () { s.classList.remove('is-highlighted'); });
        list.insertBefore(s, list.firstChild);
    }

    function reorderByCode(list) {
        const opts = vendorOptions(list);
        if (opts.length > 1) {
            opts.sort((a, b) =>
                a.textContent.trim().localeCompare(b.textContent.trim(), undefined, { numeric: true }));
            opts.forEach(el => list.appendChild(el));  // re-order DOM into code order
        }
        return opts;
    }

    selectEl.addEventListener('search', function () {
        // Defer until Choices has rendered the filtered list for this keystroke.
        requestAnimationFrame(function () {
            const list = dropdownList();
            if (!list) return;
            ensureSentinel(list);
            const opts = reorderByCode(list);
            if (opts.length < 1) return;
            if (typeof choices._highlightChoice === 'function') {
                choices._highlightChoice(opts[0]);
            }

            // Inline autocomplete: fill the field with the first match and select
            // the not-yet-typed remainder, so the next keystroke overwrites it.
            // Only when the user is adding text and the match starts with it.
            if (input && !isDeleting) {
                const typed = input.value;
                const label = opts[0].textContent.trim();
                if (typed && label.length > typed.length &&
                    label.toLowerCase().startsWith(typed.toLowerCase())) {
                    input.value = typed + label.slice(typed.length);
                    try { input.setSelectionRange(typed.length, label.length); } catch (e) { /* noop */ }
                }
            }
        });
    });

    // On open (no query yet), keep the list in code order so freshly-added
    // vendors land in their sorted position without a page reload.
    selectEl.addEventListener('showDropdown', function () {
        requestAnimationFrame(function () {
            const list = dropdownList();
            if (!list) return;
            ensureSentinel(list);
            reorderByCode(list);
        });
    });
}

function initVendorQuickAdd(opts) {
    const { choices, selectEl } = opts;
    const overlay = document.getElementById('vendorQuickAddOverlay');
    if (!choices || !selectEl || !overlay) return;

    const form = document.getElementById('vendorQuickAddForm');
    const errorBox = document.getElementById('vendorQuickAddError');
    const submitBtn = document.getElementById('vendorQuickAddSubmit');
    let vatChoices = null;

    // The sentinel option is added to the <select> before Choices init
    // (see addVendorSentinelOption), so it already leads the dropdown here.

    // Predictable typeahead: code-order results, pinned "Add Vendor", highlight.
    // openModal is a hoisted function declaration below, so it's available here.
    enhanceVendorTypeahead(choices, selectEl, openModal);

    // Remember the last real selection so opening/cancelling the modal restores it.
    let lastValue = selectEl.value && selectEl.value !== VENDOR_ADD_SENTINEL ? selectEl.value : '';

    function openModal() {
        errorBox.style.display = 'none';
        errorBox.textContent = '';
        overlay.style.display = 'flex';
        // Init the modal's VAT search-select once; keep the instance so we can
        // reset it after a successful save (form.reset() can't touch Choices' DOM).
        if (!vatChoices && typeof initVendorVatSelect === 'function') {
            vatChoices = initVendorVatSelect(overlay);
        }
    }

    function closeModal() {
        overlay.style.display = 'none';
    }

    selectEl.addEventListener('change', function () {
        if (selectEl.value === VENDOR_ADD_SENTINEL) {
            // Restore the previous real selection, then open the modal.
            choices.setChoiceByValue(lastValue || '');
            openModal();
        } else {
            lastValue = selectEl.value;
        }
    });

    document.getElementById('vendorQuickAddClose').addEventListener('click', closeModal);
    document.getElementById('vendorQuickAddCancel').addEventListener('click', closeModal);
    overlay.addEventListener('click', function (e) {
        if (e.target === overlay) closeModal();
    });

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        errorBox.style.display = 'none';
        submitBtn.disabled = true;

        fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        })
            .then(r => r.json().then(body => ({ status: r.status, body })))
            .then(({ status, body }) => {
                if (status === 200 && body.ok) {
                    // Add the new vendor and select it.
                    choices.setChoices(
                        [{ value: String(body.vendor.id), label: body.vendor.label }],
                        'value', 'label', false
                    );
                    lastValue = String(body.vendor.id);
                    choices.setChoiceByValue(String(body.vendor.id));
                    // setChoiceByValue does not emit a native `change` on the
                    // underlying <select>, so fire it ourselves — that's what
                    // the page's vendor handler listens on (AP defaults / CD bills).
                    selectEl.dispatchEvent(new Event('change', { bubbles: true }));
                    closeModal();
                    form.reset();
                    // form.reset() restores native inputs, but the Choices-enhanced
                    // VAT widget keeps its own DOM — clear it explicitly.
                    if (vatChoices) vatChoices.setChoiceByValue('');
                } else {
                    const errs = body.errors || {};
                    const first = Object.values(errs)[0] || 'Could not create vendor. Please check the fields.';
                    errorBox.textContent = first;
                    errorBox.style.display = '';
                }
            })
            .catch(() => {
                errorBox.textContent = 'Network error — vendor was not created.';
                errorBox.style.display = '';
            })
            .finally(() => { submitBtn.disabled = false; });
    });
}
