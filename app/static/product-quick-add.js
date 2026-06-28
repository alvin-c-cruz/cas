/* product-quick-add.js
   Call initProductQuickAdd() once per page when the product module is active.
   Exposes openProductModal(lineId, onSuccess) globally.  */

function initProductQuickAdd() {
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
        overlay.style.display = 'flex';
        document.getElementById('pqa_code').focus();
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
        fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
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
