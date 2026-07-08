/* Inline "+ Add Vendor" wiring for transaction vendor pickers.
   Call initVendorQuickAdd({ selectEl }) once per page.
   Requires search-select.js (initSearchSelect) and Choices to be loaded, plus
   the #vendorQuickAddOverlay modal partial to be present on the page. */

function initVendorQuickAdd(opts) {
    const selectEl = opts && opts.selectEl;
    // Optional prefix for the inserted option value (e.g. 'vendor:' when the
    // picker is a combined payee dropdown). Defaults to '' so existing callers
    // (CD form) keep inserting a bare vendor id.
    const valuePrefix = (opts && opts.valuePrefix) || '';
    const overlay = document.getElementById('vendorQuickAddOverlay');
    if (!selectEl || !overlay || typeof initSearchSelect !== 'function') return;

    const form = document.getElementById('vendorQuickAddForm');
    const errorBox = document.getElementById('vendorQuickAddError');
    const submitBtn = document.getElementById('vendorQuickAddSubmit');
    let vatChoices = null;
    let wtChoices = null;

    function openModal() {
        errorBox.style.display = 'none';
        errorBox.textContent = '';
        overlay.style.display = 'flex';
        // Init the modal's VAT + WT search-selects once; keep the instances so we
        // can reset them after a successful save (form.reset() can't touch the
        // Choices-managed DOM).
        if (!vatChoices && typeof initVendorVatSelect === 'function') {
            vatChoices = initVendorVatSelect(overlay);
        }
        if (!wtChoices && typeof initVendorWtSelect === 'function') {
            wtChoices = initVendorWtSelect(overlay);
        }
    }

    function closeModal() {
        overlay.style.display = 'none';
    }

    // Build the picker via the shared search-select, pinning "Add Vendor" as the
    // always-available add-action. The sentinel value stays '__add_vendor__' so
    // the AP/CD page change-handlers' existing guards keep working.
    const choices = initSearchSelect(selectEl, {
        choicesOptions: { searchResultLimit: 50 },
        addAction: { value: '__add_vendor__', label: '➕ Add Vendor…', onSelect: openModal },
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
                    const newVal = valuePrefix + String(body.vendor.id);
                    choices.setChoices(
                        [{ value: newVal, label: body.vendor.label }],
                        'value', 'label', false
                    );
                    choices.setChoiceByValue(newVal);
                    // setChoiceByValue does not emit a native `change` on the
                    // underlying <select>, so fire it ourselves — that's what
                    // the page's vendor handler listens on (AP defaults / CD bills).
                    selectEl.dispatchEvent(new Event('change', { bubbles: true }));
                    closeModal();
                    form.reset();
                    // form.reset() restores native inputs, but the Choices-enhanced
                    // VAT/WT widgets keep their own DOM — clear them explicitly.
                    if (vatChoices) vatChoices.setChoiceByValue('');
                    if (wtChoices) wtChoices.removeActiveItems();
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
