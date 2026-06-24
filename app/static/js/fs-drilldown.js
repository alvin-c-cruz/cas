/**
 * fs-drilldown.js  — Financial Statement drill-down modal + expander toggles.
 *
 * Expander: clicking [data-fs-expand] toggles visibility of sibling rows that
 * carry the matching [data-fs-children] value.
 *
 * Drill-down: clicking any [data-account-id] row (that is NOT the expander
 * control itself) fetches /reports/account-ledger and populates the shared
 * #ledgerModal partial.
 *
 * For BS lines the caller passes data-asof; the JS derives start = Jan 1 of
 * that year and end = the as-of date.
 * For IS/CF lines the caller passes data-start and data-end.
 */
(function () {
    'use strict';

    // ── helpers ──────────────────────────────────────────────────────────────

    function fmt(val) {
        var n = parseFloat(val);
        if (isNaN(n)) return '—';
        var abs = Math.abs(n).toLocaleString('en-PH', {minimumFractionDigits: 2, maximumFractionDigits: 2});
        return (n < 0 ? '(' : '') + '₱' + abs + (n < 0 ? ')' : '');
    }

    // ── expander (expand/collapse children rows) ─────────────────────────────

    document.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-fs-expand]');
        if (!btn) return;
        e.stopPropagation();
        var key = btn.getAttribute('data-fs-expand');
        var rows = document.querySelectorAll('[data-fs-children="' + key + '"]');
        var open = btn.getAttribute('aria-expanded') === 'true';
        rows.forEach(function (r) { r.hidden = open; });
        btn.setAttribute('aria-expanded', open ? 'false' : 'true');
        btn.querySelector('.fs-caret').textContent = open ? '▶' : '▼';
    });

    // ── modal helpers ─────────────────────────────────────────────────────────

    var modal    = document.getElementById('ledgerModal');
    var loading  = document.getElementById('ledgerModalLoading');
    var errorEl  = document.getElementById('ledgerModalError');
    var content  = document.getElementById('ledgerModalContent');
    var tbody    = document.getElementById('ledgerModalBody');
    var emptyEl  = document.getElementById('ledgerModalEmpty');
    var codeEl   = document.getElementById('ledgerModalCode');
    var titleEl  = document.getElementById('ledgerModalTitle');
    var openEl   = document.getElementById('ledgerModalOpening');
    var closeEl  = document.getElementById('ledgerModalClosing');
    var closeBtn = document.getElementById('ledgerModalClose');

    if (!modal) return;   // modal partial not included — bail

    function showModal() { modal.hidden = false; document.body.style.overflow = 'hidden'; }
    function hideModal() { modal.hidden = true;  document.body.style.overflow = ''; }

    function resetModal() {
        loading.hidden = true;
        errorEl.hidden = true;
        content.hidden = true;
        emptyEl.hidden = true;
        tbody.innerHTML = '';
    }

    closeBtn.addEventListener('click', hideModal);

    modal.addEventListener('click', function (e) {
        if (e.target === modal) hideModal();
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !modal.hidden) hideModal();
    });

    // ── drill-down click handler ──────────────────────────────────────────────

    document.addEventListener('click', function (e) {
        // Ignore clicks that originate from the expander button
        if (e.target.closest('[data-fs-expand]')) return;

        var row = e.target.closest('[data-account-id]');
        if (!row) return;

        var accountId = row.getAttribute('data-account-id');
        if (!accountId) return;

        var start, end;
        var asof = row.getAttribute('data-asof');
        if (asof) {
            // Balance Sheet: start = Jan 1 of as-of year, end = as-of date
            start = asof.substring(0, 4) + '-01-01';
            end   = asof;
        } else {
            start = row.getAttribute('data-start') || '';
            end   = row.getAttribute('data-end')   || '';
        }

        resetModal();
        showModal();
        loading.hidden = false;

        var url = '/reports/account-ledger?account_id=' + encodeURIComponent(accountId)
                  + '&start=' + encodeURIComponent(start)
                  + '&end='   + encodeURIComponent(end);

        fetch(url, {credentials: 'same-origin'})
            .then(function (r) { return r.json(); })
            .then(function (data) {
                loading.hidden = true;
                if (data.error) {
                    errorEl.textContent = data.error;
                    errorEl.hidden = false;
                    return;
                }
                codeEl.textContent  = data.account.code ? data.account.code + ' — ' : '';
                titleEl.textContent = data.account.name;
                openEl.textContent  = fmt(data.opening);
                closeEl.textContent = fmt(data.closing);

                if (!data.lines || data.lines.length === 0) {
                    emptyEl.hidden = false;
                } else {
                    data.lines.forEach(function (ln) {
                        var tr = document.createElement('tr');
                        tr.innerHTML =
                            '<td>' + (ln.date || '') + '</td>' +
                            '<td>' + escHtml(String(ln.source || '')) + '</td>' +
                            '<td>' + escHtml(String(ln.particulars || '')) + '</td>' +
                            '<td class="num-col">' + (ln.debit  ? fmt(ln.debit)  : '') + '</td>' +
                            '<td class="num-col">' + (ln.credit ? fmt(ln.credit) : '') + '</td>' +
                            '<td class="num-col">' + fmt(ln.balance) + '</td>';
                        tbody.appendChild(tr);
                    });
                }
                content.hidden = false;
            })
            .catch(function (err) {
                loading.hidden = true;
                errorEl.textContent = 'Could not load ledger data. Please try again.';
                errorEl.hidden = false;
            });
    });

    function escHtml(s) {
        return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }
})();
