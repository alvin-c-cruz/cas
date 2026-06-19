/* Turns the vendor "Default VAT Category" <select> inside `root` into a
   Choices.js search-select. Idempotent: safe to call again on the same root
   (e.g. each time the quick-add modal opens). Requires Choices to be loaded. */
function initVendorVatSelect(root) {
    if (!root || typeof Choices === 'undefined') return null;
    const sel = root.querySelector('select.vendor-vat-select');
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

/* Turns the vendor "Withholding Tax" <select multiple> inside `root` into a
   Choices.js searchable multi-select (removable chips). Scales to many WT
   codes where a checkbox grid would not. Idempotent like initVendorVatSelect.
   The native <select multiple> still submits each selected option as a
   `withholding_tax_ids` param, so the backend is unchanged. */
function initVendorWtSelect(root) {
    if (!root || typeof Choices === 'undefined') return null;
    const sel = root.querySelector('select.vendor-wt-select');
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
    });
}
