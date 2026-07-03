"""Smart proper-case for RIC account titles. Deterministic + reusable.
Title-cases each maximal letter-run; keeps true acronyms uppercase and leaves
digits/%/$/parens/hyphens untouched, so codes/serials/percentages survive."""
import re

ACRONYMS = {
    'BPI','SSS','HDMF','NHMFC','VAT','CWT','WHT','PDC','RCC','RLMC','RIC','TIN',
    'FO','SE','AE','HMO','ATM','QC',
}
SPECIAL = {'PHILHEALTH': 'PhilHealth', "X'MAS": "X'mas"}
MINOR = {'a','an','and','of','to','the','on','in','for','or','by','with','at','as'}
ORD = {'st','nd','rd','th'}
WORD = re.compile(r"[A-Za-z][A-Za-z.']*")


def _case_word(w, is_first, prev_is_digit):
    if prev_is_digit and w.lower() in ORD:
        return w.lower()
    if w.upper() in SPECIAL:
        return SPECIAL[w.upper()]
    bare = re.sub(r"[.']", '', w).upper()
    if bare in ACRONYMS:
        return w.upper()
    low = w.lower()
    if not is_first and low in MINOR:
        return low
    out, capped = [], False
    for ch in w:
        if not capped and ch.isalpha():
            out.append(ch.upper()); capped = True
        else:
            out.append(ch.lower())
    return ''.join(out)


def proper_case(title):
    def repl(m):
        pre = title[:m.start()]
        is_first = not any(c.isalpha() for c in pre)
        prev_is_digit = bool(pre) and pre[-1].isdigit()
        return _case_word(m.group(0), is_first, prev_is_digit)
    return WORD.sub(repl, title)
