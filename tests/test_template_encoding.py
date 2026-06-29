"""Guard against double-encoded UTF-8 (mojibake) in templates.

A template read as Windows-1252/latin-1 and re-saved as UTF-8 double-encodes every glyph
(₱ -> â‚±, — -> â€", 📋 -> ðŸ"‹). The file stays "valid UTF-8", so browsers render the garbage
(it bit base.html + 18 other templates, surfaced 2026-06-29). This test fails if any template
contains a suspect run that cleanly reverses one double-encoding layer.
"""
import glob
import os

import pytest

# Chars a single mojibake byte (0x80-0xFF) can decode to under a permissive cp1252.
_FWD = {}
for _b in range(0x80, 0x100):
    try:
        _FWD[_b] = bytes([_b]).decode("cp1252")
    except UnicodeDecodeError:
        _FWD[_b] = chr(_b)
_REV = {c: b for b, c in _FWD.items()}
_SUSPECT = set(_REV)

_ROOT = os.path.join(os.path.dirname(__file__), os.pardir, "app")


def _mojibake_runs(text):
    """Return the suspect runs in `text` that cleanly reverse to fewer-suspect valid UTF-8."""
    found, i, n = [], 0, len(text)
    while i < n:
        if text[i] in _SUSPECT:
            j = i
            while j < n and text[j] in _SUSPECT:
                j += 1
            run = text[i:j]
            try:
                out = bytes(_REV[c] for c in run).decode("utf-8")
                if sum(c in _SUSPECT for c in out) < len(run):
                    found.append(run)
            except (KeyError, UnicodeDecodeError):
                pass
            i = j
        else:
            i += 1
    return found


def _templates():
    return sorted(glob.glob(os.path.join(_ROOT, "**", "*.html"), recursive=True))


@pytest.mark.unit
def test_no_double_encoded_templates():
    offenders = []
    for path in _templates():
        with open(path, encoding="utf-8") as fh:
            if _mojibake_runs(fh.read()):
                offenders.append(os.path.relpath(path, os.path.join(_ROOT, os.pardir)))
    assert not offenders, (
        "Double-encoded UTF-8 (mojibake) found in templates — re-save as clean UTF-8:\n  "
        + "\n  ".join(offenders)
    )
