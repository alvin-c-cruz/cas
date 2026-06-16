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
