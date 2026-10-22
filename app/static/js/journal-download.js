// Download Journal (the SI, CR, AP, CDV and JV lists) takes its period from the
// From / To boxes of its own filter form as they stand at the click, so a date typed
// without pressing Filter still counts. A blank box or a To before From is refused
// with the browser's own field message rather than downloading some other period.
(function () {
    document.querySelectorAll('[data-journal-download]').forEach(function (download) {
        const boxes = download.closest('form').elements;
        const fromBox = boxes.date_from;
        const toBox = boxes.date_to;
        [fromBox, toBox].forEach(function (box) {
            box.addEventListener('input', function () { box.setCustomValidity(''); });
            box.addEventListener('blur', function () { box.setCustomValidity(''); });
        });
        download.addEventListener('click', function (e) {
            const from = fromBox.value;
            const to = toBox.value;
            let bad = null;
            let msg = '';
            if (!from) { bad = fromBox; msg = 'Enter the From date to download the journal.'; }
            else if (!to) { bad = toBox; msg = 'Enter the To date to download the journal.'; }
            else if (from > to) { bad = toBox; msg = 'To must be on or after From.'; }
            if (bad) {
                e.preventDefault();
                bad.setCustomValidity(msg);
                bad.reportValidity();
                return;
            }
            const url = new URL(download.href, window.location.href);
            url.searchParams.set('mode', 'custom');
            url.searchParams.set('date_from', from);
            url.searchParams.set('date_to', to);
            download.href = url.toString();
        });
    });
})();
