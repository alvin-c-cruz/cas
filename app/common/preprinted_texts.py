"""Shared layout-text logic for the pre-printed form designers (SI / CRV / APV).

Free-text, LAYOUT-ONLY elements (signatory lines + arbitrary user text) are the
ONE part of a pre-printed layout with no document-data binding, so they are the
only piece extracted to a shared helper; everything data-bound stays cloned per
document.

`clean_texts(raw, defaults)` is a **forward-compatible reader migration**: it
accepts the legacy DICT shape (`{id: box}`) OR the new LIST shape
(`[{id, text, ...}]`) and ALWAYS returns a sanitized LIST. `get_layout()` falls
back to the module DEFAULT on any raise, so a bug here would QUIETLY destroy a
saved layout — this function must never throw on plausible stored JSON.

Canvas/font/length bounds are identical across all pre-printed documents (same
paper), so they live here rather than being threaded in per call.
"""
import re

CANVAS_W = 912       # 9.5in @96dpi (widest supported paper)
CANVAS_H = 1008      # 10.5in @96dpi
SAFE_MARGIN = 48
FONT_MIN, FONT_MAX = 6, 72
TEXT_MAXLEN = 200
MAX_TEXTS = 50
WIDTH_MIN, WIDTH_MAX = 10, CANVAS_W

_ID_RE = re.compile(r'[^a-zA-Z0-9_-]')


def _clamp(value, lo, hi, fallback):
    try:
        n = int(round(float(value)))
    # OverflowError joins the two: json.loads("1e999") is float inf and round(inf)
    # refuses to make an int of it -- valid JSON, no try/except upstream, a 500.
    except (TypeError, ValueError, OverflowError):
        return fallback
    return max(lo, min(hi, n))


def clean_wrap_width(raw, default=0):
    """A layout element's wrap width. 0 is a real value meaning UNSET: the element is
    content-sized and stays on one line, which is what every layout saved before
    2026-09-06 means by having no `width` key at all.

    Not `_clamp`: WIDTH_MIN is 10, so clamping would read "no width" as a 10px sliver and
    shred every stored layout on its next read. Sub-minimum values snap UP instead, so a
    stray 3px drag cannot silently un-wrap an element somebody sized on purpose.

    OverflowError is caught for the same reason `_clamp` catches it: json.loads("1e999")
    is float inf, and int() refuses it. This module must never throw on stored JSON --
    get_layout() swallows the raise and the client's saved layout is quietly lost.
    """
    try:
        n = int(float(raw))
    except (TypeError, ValueError, OverflowError):
        return default
    if n <= 0:
        return 0
    return max(WIDTH_MIN, min(WIDTH_MAX, n))


def _clean_id(raw, fallback):
    """A safe DOM/dedupe slug: alphanumerics + `_`/`-`, capped, non-empty."""
    s = _ID_RE.sub('', str(raw if raw is not None else ''))[:40]
    return s or fallback


def _merge_text(src, base):
    """One sanitized text: `src` values over `base` (a default or a bare skeleton)."""
    src = src if isinstance(src, dict) else {}
    text = src.get('text', base['text'])
    text = str(text)[:TEXT_MAXLEN] if text is not None else base['text']
    return {
        'id': base['id'],
        'text': text,
        'x': _clamp(src.get('x'), SAFE_MARGIN, CANVAS_W - SAFE_MARGIN, base['x']),
        'y': _clamp(src.get('y'), 0, CANVAS_H, base['y']),
        'fontSize': _clamp(src.get('fontSize'), FONT_MIN, FONT_MAX, base['fontSize']),
        'bold': bool(src.get('bold', base['bold'])),
        'hidden': bool(src.get('hidden', base['hidden'])),
        # Optional wrap width; absent from every blob saved before 2026-09-06 -> 0.
        'width': clean_wrap_width(src.get('width'), base.get('width', 0)),
    }


def clean_texts(raw, defaults):
    """Return a sanitized LIST of layout texts from `raw` over the `defaults` list.

    - `raw` is a legacy DICT (`id -> box`): union each stored override over the
      default list BY ID, so every default signatory survives at its stored
      position (the forward-compat migration path — legacy layouts always held
      all signatories).
    - `raw` is a LIST: the stored list IS the set of texts — sanitize each entry,
      anchor known default ids on their default, dedupe ids, cap at MAX_TEXTS. A
      default the user deleted stays deleted (NOT re-injected).
    - `raw` is missing/invalid: return the full default list.
    """
    default_by_id = {d['id']: d for d in defaults}

    if isinstance(raw, dict):
        return [_merge_text(raw.get(d['id']), d) for d in defaults]

    if isinstance(raw, list):
        out, seen = [], set()
        for i, e in enumerate(raw[:MAX_TEXTS]):
            if not isinstance(e, dict):
                continue
            tid = _clean_id(e.get('id'), f't{i}')
            if tid in seen:
                continue
            seen.add(tid)
            base = default_by_id.get(tid) or {
                'id': tid, 'text': '', 'x': 0, 'y': 0,
                'fontSize': 10, 'bold': False, 'hidden': False, 'width': 0,
            }
            out.append(_merge_text(e, base))
        return out

    # Defaults pass through untouched EXCEPT that the width key is filled in. A consumer's
    # DEFAULT list predates the key, and this is the branch a fresh layout takes, so
    # without this it is the one shape a template reading `t.width` never sees it on.
    # Deliberately not _merge_text(d, d): that would re-clamp x/y/fontSize on values that
    # are the module's own constants, turning a default nobody edited into a moving target.
    return [dict(d, width=clean_wrap_width(d.get('width'))) for d in defaults]
