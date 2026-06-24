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

/* Turns the customer "Withholding Tax" <select multiple> inside `root` into a
   Choices.js searchable multi-select (removable chips), mirroring the vendor WT
   picker. Customer.withholding_taxes is many-to-many (customer_withholding_taxes),
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
    });
}
