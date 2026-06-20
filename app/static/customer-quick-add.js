/* Inline "+ Add Customer" wiring for transaction customer pickers.
   Call initCustomerQuickAdd({ selectEl }) once per page.
   Requires search-select.js (initSearchSelect) and Choices to be loaded, plus
   the #customerQuickAddOverlay modal partial to be present on the page. */

function initCustomerQuickAdd(opts) {
    const selectEl = opts && opts.selectEl;
    const overlay = document.getElementById('customerQuickAddOverlay');
    if (!selectEl || !overlay || typeof initSearchSelect !== 'function') return null;

    const form = document.getElementById('customerQuickAddForm');
    const errorBox = document.getElementById('customerQuickAddError');
    const submitBtn = document.getElementById('customerQuickAddSubmit');
    let vatChoices = null;
    let wtChoices = null;

    function openModal() {
        errorBox.style.display = 'none';
        errorBox.textContent = '';
        overlay.style.display = 'flex';
        if (!vatChoices && typeof initCustomerVatSelect === 'function') {
            vatChoices = initCustomerVatSelect(overlay);
        }
        if (!wtChoices && typeof initCustomerWtSelect === 'function') {
            wtChoices = initCustomerWtSelect(overlay);
        }
    }

    function closeModal() {
        overlay.style.display = 'none';
    }

    const choices = initSearchSelect(selectEl, {
        choicesOptions: { searchResultLimit: 50 },
        addAction: { value: '__add_customer__', label: '➕ Add Customer…', onSelect: openModal },
    });

    document.getElementById('customerQuickAddClose').addEventListener('click', closeModal);
    document.getElementById('customerQuickAddCancel').addEventListener('click', closeModal);
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
                    choices.setChoices(
                        [{ value: String(body.customer.id), label: body.customer.label }],
                        'value', 'label', false
                    );
                    choices.setChoiceByValue(String(body.customer.id));
                    selectEl.dispatchEvent(new Event('change', { bubbles: true }));
                    closeModal();
                    form.reset();
                    if (vatChoices) vatChoices.setChoiceByValue('');
                    if (wtChoices) wtChoices.setChoiceByValue('');
                } else {
                    const errs = body.errors || {};
                    const first = Object.values(errs)[0] || 'Could not create customer. Please check the fields.';
                    errorBox.textContent = first;
                    errorBox.style.display = '';
                }
            })
            .catch(() => {
                errorBox.textContent = 'Network error — customer was not created.';
                errorBox.style.display = '';
            })
            .finally(() => { submitBtn.disabled = false; });
    });

    return choices;
}
