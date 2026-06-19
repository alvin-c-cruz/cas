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

/* Turns the customer "Withholding Tax" <select> inside `root` into a Choices.js
   single search-select. Customer carries a single default_wt_code (unlike the
   vendor multi-select), so this is a plain searchable single picker. */
function initCustomerWtSelect(root) {
    if (!root || typeof Choices === 'undefined') return null;
    const sel = root.querySelector('select.customer-wt-select');
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
