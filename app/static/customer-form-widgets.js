/* Turns the customer "Default VAT Category" <select> inside `root` into a
   Choices.js search-select. Idempotent: safe to call again on the same root.
   Requires Choices to be loaded. */
function initCustomerVatSelect(root) {
    if (!root || typeof Choices === 'undefined') return null;
    const sel = root.querySelector('select.customer-vat-select');
    if (!sel || sel.dataset.choicesReady === '1') return null;
    sel.dataset.choicesReady = '1';
    return new Choices(sel, {
        searchEnabled: true,
        itemSelectText: '',
        shouldSort: false,
        searchResultLimit: 50,
        allowHTML: false,
    });
}

function _cwEscHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                    .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

/* Turns the customer "Withholding Tax" <select multiple> inside `root` into a
   Choices.js searchable multi-select (removable chips), mirroring the vendor WT
   picker. The dropdown shows the full `CODE — Name (rate%)` (for search), but the
   selected chip shows the CODE only (compact), matching the line-item VT/WT
   convention — each <option> carries data-custom-properties='{"code":...}'.
   Customer.withholding_taxes is many-to-many (customer_withholding_taxes),
   submitted as `withholding_tax_ids`, so the backend is unchanged. Idempotent. */
function initCustomerWtSelect(root) {
    if (!root || typeof Choices === 'undefined') return null;
    const sel = root.querySelector('select.customer-wt-multi-select');
    if (!sel || sel.dataset.choicesReady === '1') return null;
    sel.dataset.choicesReady = '1';
    return new Choices(sel, {
        searchEnabled: true,
        removeItemButton: true,
        itemSelectText: '',
        shouldSort: false,
        searchResultLimit: 50,
        allowHTML: false,
        placeholderValue: 'Search or select withholding tax…',
        callbackOnCreateTemplates: function (tmpl) {
            return {
                // Selected chip = code only; keep the remove button (multi-select).
                item: function (cfg, data) {
                    const cn = cfg.classNames;
                    const code = (data.customProperties && data.customProperties.code) || data.value || '—';
                    return tmpl(
                        '<div class="' + _cwEscHtml(cn.item) + ' ' + _cwEscHtml(cn.itemSelectable) +
                        (data.highlighted ? ' ' + _cwEscHtml(cn.highlightedState) : '') + '" ' +
                        'data-item data-id="' + _cwEscHtml(String(data.id)) + '" ' +
                        'data-value="' + _cwEscHtml(String(data.value)) + '" ' +
                        (data.active ? 'aria-selected="true" ' : '') +
                        (data.disabled ? 'aria-disabled="true" ' : '') +
                        'data-deletable>' + _cwEscHtml(String(code)) +
                        '<button type="button" class="' + _cwEscHtml(cn.button) +
                        '" aria-label="Remove withholding tax" data-button>Remove item</button>' +
                        '</div>'
                    );
                }
            };
        }
    });
}
