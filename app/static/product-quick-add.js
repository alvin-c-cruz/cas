/* product-quick-add.js
   Call initProductQuickAdd() once per page when the product module is active.
   Exposes openProductModal(lineId, onSuccess) globally.
   PROD-QA (owner, 22 Nov 2026: "the two should be identical"): the box renders the Products page's own fields, each
   named "pqa-<field>" so that no id repeats one of the page around it. The prefix comes off here, before posting to
   the same view the Products page posts to (products.create), which answers with the whole product. */

function initProductQuickAdd() {
    var PREFIX = 'pqa-';
    const overlay   = document.getElementById('productQuickAddOverlay');
    const form      = document.getElementById('productQuickAddForm');
    const errorBox  = document.getElementById('productQuickAddError');
    const submitBtn = document.getElementById('productQuickAddSubmit');
    if (!overlay || !form) return;

    let _onSuccess = null;

    window.openProductModal = function (lineId, onSuccess) {
        _onSuccess = onSuccess;
        errorBox.style.display = 'none';
        errorBox.textContent = '';
        form.reset();
        // reset() fires no change event: tell the Active switch and the inventory fields what they now show.
        // Not bubbling, so no handler of the page around the box takes it for one of its own fields.
        form.querySelectorAll('select, input[type="checkbox"]').forEach(function (el) {
            el.dispatchEvent(new Event('change', { bubbles: false }));
        });
        overlay.style.display = 'flex';
        // The line's product picker (Choices) closes on the next animation frame and takes the focus back as it
        // does: put the cursor in Name after that.
        var nameEl = document.getElementById('pqa-name');
        nameEl.focus();
        requestAnimationFrame(function () { requestAnimationFrame(function () { nameEl.focus(); }); });
    };

    function closeModal() {
        overlay.style.display = 'none';
        _onSuccess = null;
    }

    document.getElementById('productQuickAddClose').addEventListener('click', closeModal);
    document.getElementById('productQuickAddCancel').addEventListener('click', closeModal);
    overlay.addEventListener('click', function (e) { if (e.target === overlay) closeModal(); });

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        errorBox.style.display = 'none';
        submitBtn.disabled = true;
        // Every value, a multiple select's included, under its field's own name.
        var fd = new FormData();
        new FormData(form).forEach(function (v, k) {
            fd.append(k.indexOf(PREFIX) === 0 ? k.slice(PREFIX.length) : k, v);
        });
        fetch(form.action, {
            method: 'POST',
            body: fd,
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        })
        .then(r => r.json().then(body => ({ status: r.status, body })))
        .then(function ({ status, body }) {
            if (status === 200 && body.ok) {
                if (_onSuccess) _onSuccess(body.product);
                closeModal();
            } else {
                const errs = body.errors || {};
                const first = Object.values(errs)[0] || 'Could not create product. Please check the fields.';
                errorBox.textContent = first;
                errorBox.style.display = '';
            }
        })
        .catch(function () {
            errorBox.textContent = 'Network error — product was not saved.';
            errorBox.style.display = '';
        })
        .finally(function () { submitBtn.disabled = false; });
    });
}
