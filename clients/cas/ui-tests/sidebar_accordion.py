"""Sidebar accordion regression spec (FEAT-SIDEBAR-ACCORDION).

Proves only one .nav-label-collapsible section is expanded at a time, that
re-clicking the open section collapses it (zero-open is valid), that the
single `sidebar:expandedSection` localStorage key tracks the open section,
that a stale/unknown saved section name falls back to the first area, and
that an active nav-item's section wins over any saved state on load.

Admin-only: covers area-* + admin + accounting-oversight section types. The
'staff' section type (accountant-role only) is not separately covered -- the
JS branches on no section-type distinction (pure data-section string
equality), so re-testing it under a second role would exercise identical
code, not new logic.
"""
import sys
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness

results = []
def check(name, ok, detail=""):
    results.append((bool(ok), name, detail)); print(("PASS " if ok else "FAIL ") + name + (("  -- " + detail) if detail else ""))

def expanded_sections(page):
    """data-section values of every .nav-label-collapsible NOT carrying .collapsed."""
    return page.eval_on_selector_all(
        ".nav-label-collapsible",
        "els => els.filter(e => !e.classList.contains('collapsed')).map(e => e.getAttribute('data-section'))"
    )

def storage_value(page):
    return page.evaluate("() => localStorage.getItem('sidebar:expandedSection')")

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=200)
    b = harness.base_url()
    harness.login(page, "admin")
    page.goto(b + "/dashboard", wait_until="networkidle")

    labels = page.locator(".nav-label-collapsible")
    count = labels.count()
    check("at least 2 collapsible sections present (admin: areas + admin + accounting-oversight)", count >= 2, "count=%d" % count)
    section_names = [labels.nth(i).get_attribute("data-section") for i in range(count)]

    # ---- Load-time invariant: at most one open, storage matches DOM ----
    open_now = expanded_sections(page)
    check("load: at most one section expanded", len(open_now) <= 1, str(open_now))
    check("load: localStorage key matches the open section", storage_value(page) == (open_now[0] if open_now else ""),
          "storage=%r open=%r" % (storage_value(page), open_now))

    # ---- Click a DIFFERENT section: it opens, everything else closes ----
    current = open_now[0] if open_now else None
    target = next(s for s in section_names if s != current)
    page.locator('.nav-label-collapsible[data-section="%s"]' % target).click()
    after_click = expanded_sections(page)
    check("click other section: exactly that one is open", after_click == [target], str(after_click))
    check("click other section: storage updated", storage_value(page) == target, storage_value(page))

    # ---- Click a THIRD section: previous one closes, new one opens (mutual exclusivity, not just a 2-section toggle) ----
    third = next((s for s in section_names if s != target), None)
    if third:
        page.locator('.nav-label-collapsible[data-section="%s"]' % third).click()
        after_third = expanded_sections(page)
        check("click a third section: only the third is open", after_third == [third], str(after_third))
        target = third

    # ---- Re-click the currently-open section: it collapses, zero sections open ----
    page.locator('.nav-label-collapsible[data-section="%s"]' % target).click()
    after_toggle_off = expanded_sections(page)
    check("re-click open section: collapses to zero open", after_toggle_off == [], str(after_toggle_off))
    check("re-click open section: storage cleared", storage_value(page) == "", storage_value(page))

    # ---- Reload with zero open, no active nav item on /dashboard -> falls back to first area ----
    page.reload(wait_until="networkidle")
    after_reload = expanded_sections(page)
    check("reload with cleared storage: falls back to a section", len(after_reload) == 1, str(after_reload))

    # ---- Stale/unknown saved section name is rejected, falls back to the first area ----
    page.evaluate("() => localStorage.setItem('sidebar:expandedSection', 'area-totally-bogus-section')")
    page.reload(wait_until="networkidle")
    after_bogus = expanded_sections(page)
    first_area = next(s for s in section_names if s.startswith("area-"))
    check("stale/unknown saved section name falls back to first area", after_bogus == [first_area], str(after_bogus))
    check("stale name is overwritten in storage, not left dangling", storage_value(page) == first_area, storage_value(page))

    # ---- Active nav-item's section wins over a different saved value ----
    other_area = next((s for s in section_names if s.startswith("area-") and s != first_area), None)
    if other_area:
        page.evaluate(
            "(s) => localStorage.setItem('sidebar:expandedSection', s)", other_area
        )
        page.goto(b + "/customers", wait_until="networkidle")
        after_active_nav = expanded_sections(page)
        check("active nav-item's section overrides a different saved section",
              after_active_nav == ["area-sales"], str(after_active_nav))
        check("active section is written back to storage", storage_value(page) == "area-sales", storage_value(page))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, name, d in results:
        if not ok: print("  FAILED:", name, "--", d)
