// transaction-utils.js
// Shared pure utilities for all transaction forms.
// NOTE: amtBlur expects updateLineItem(id, field, value) to be defined by the host form.

function fmt(n) {
    return n.toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtNum(n) {
    return n > 0
        ? n.toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : '—';
}

function amtFmt(n) {
    return (n || 0).toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function amtFocus(el) {
    const n = parseFloat(el.value.replace(/,/g, '')) || 0;
    el.value = n.toFixed(2);
    el.select();
}

function amtBlur(el, id) {
    const n = parseFloat(el.value.replace(/,/g, '')) || 0;
    el.value = amtFmt(n);
    updateLineItem(id, 'amount', n);
}

// qtyBlur / upBlur: called by SI and AP (which use updateLineItem).
// CDV/CRV define their own expQtyBlur/expUpBlur / revQtyBlur/revUpBlur.
function qtyBlur(el, id) {
    const n = parseFloat(el.value.replace(/,/g, '')) || null;
    el.value = n != null ? amtFmt(n) : '';
    updateLineItem(id, 'quantity', n);
    updateDerivedAmount(id);
}

function upBlur(el, id) {
    const n = parseFloat(el.value.replace(/,/g, '')) || null;
    el.value = n != null ? amtFmt(n) : '';
    updateLineItem(id, 'unit_price', n);
    updateDerivedAmount(id);
}

function escHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
