/* The "Report a problem" sheet, on every signed-in CAS page (app/templates/base.html).
   Ported from Sanay's public/report.js (C:\envs\sanay). What changed for CAS, and why, is in
   app-docs/superpowers/specs/2026-10-15-bug-reports-design.md beside the checkout.
   From the moment a page opens it records the last clicks (what was clicked, never what was typed), page changes,
   errors, and failed or slow requests to this site. The record lives in sessionStorage, so it spans the tab's page
   loads: CAS loads a whole page on every save. CasReport.open() takes a picture of the page, then shows a sheet for
   the user's message. A report that cannot be sent waits in IndexedDB and goes out when a CAS page next opens, or
   the browser comes back online, for the same user. */
(function () {
  "use strict";
  if (window.CasReport) return;

  var script = document.currentScript;
  var ENDPOINT = (script && script.getAttribute("data-endpoint")) || "/bug-reports";
  var LIB_URL = (script && script.getAttribute("data-lib")) || "/static/vendor/modern-screenshot-4.7.0.js";

  var LIMIT = { taps: 30, pages: 20, errors: 20, requests: 20, sizes: 40 };
  var SLOW_MS = 3000;
  var MAX_SIDE = 1600;
  var MAX_PICTURE = 300 * 1024;
  var LOG_KEY = "cas.report.log";
  var log = { taps: [], pages: [], errors: [], requests: [], sizes: [] };

  /* The tab's earlier pages left their record in sessionStorage; without storage it starts fresh on each page. */
  try {
    var saved = JSON.parse(window.sessionStorage.getItem(LOG_KEY) || "null");
    if (saved && typeof saved === "object") {
      Object.keys(log).forEach(function (k) { if (Array.isArray(saved[k])) log[k] = saved[k].slice(-LIMIT[k]); });
    }
  } catch (e) {}
  function save() { try { window.sessionStorage.setItem(LOG_KEY, JSON.stringify(log)); } catch (e) {} }

  function stamp() { return new Date().toISOString(); }
  function keep(list, item, max) { list.push(item); while (list.length > max) list.shift(); save(); }
  function short(s, n) { return String(s == null ? "" : s).slice(0, n); }
  /** The page as CAS addresses it: reports and lists are driven by their query string. */
  function here() { return location.pathname + location.search; }

  /** An element for the click log: tag, id, label and visible text. For fields, only their type, never their value. */
  function describe(el) {
    var tag = el.tagName ? String(el.tagName).toLowerCase() : "?";
    var s = tag + (el.id ? "#" + el.id : "");
    var label = el.getAttribute ? el.getAttribute("aria-label") || el.getAttribute("title") : null;
    if (label) s += " [" + short(label, 40) + "]";
    if (tag === "input" || tag === "textarea" || tag === "select") {
      if (el.type) s += " (" + el.type + ")";
    } else {
      var text = String(el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40);
      if (text) s += ' "' + text + '"';
    }
    return s;
  }

  document.addEventListener("click", function (e) {
    var t = e && e.target;
    var el = t && t.closest ? t.closest("button,a,input,select,textarea,label,[role=button],[data-f],[id]") : null;
    if (el) keep(log.taps, { t: stamp(), what: describe(el) }, LIMIT.taps);
  }, true);

  function page() { keep(log.pages, { t: stamp(), path: here() }, LIMIT.pages); }
  page();
  ["pushState", "replaceState"].forEach(function (k) {
    var orig = history[k];
    if (typeof orig !== "function") return;
    history[k] = function () { var r = orig.apply(this, arguments); page(); return r; };
  });
  window.addEventListener("popstate", page);

  window.addEventListener("error", function (e) {
    keep(log.errors, { t: stamp(), message: short(e && e.message || "error", 300), at: (e && e.filename || "") + ":" + (e && e.lineno || 0) }, LIMIT.errors);
  });
  window.addEventListener("unhandledrejection", function (e) {
    var r = e && e.reason;
    keep(log.errors, { t: stamp(), message: "unhandled: " + short(r && r.message || r, 300) }, LIMIT.errors);
  });
  if (console && typeof console.error === "function") {
    var origError = console.error;
    console.error = function () {
      try { keep(log.errors, { t: stamp(), message: "console: " + short(Array.prototype.map.call(arguments, String).join(" "), 300) }, LIMIT.errors); } catch (x) {}
      return origError.apply(this, arguments);
    };
  }

  /** Requests to this site that failed or took over 3 s: method, path without its query string, status, time. */
  if (typeof window.fetch === "function") {
    var origFetch = window.fetch;
    window.fetch = function (input, init) {
      var url = typeof input === "string" ? input : (input && input.url) || String(input);
      var method = String((init && init.method) || (input && input.method) || "GET").toUpperCase();
      var u = null;
      try { u = new URL(url, location.href); } catch (x) {}
      var p = origFetch.apply(window, arguments);
      if (!u || u.origin !== location.origin) return p;
      var t0 = Date.now();
      var path = u.pathname;
      return p.then(function (res) {
        var ms = Date.now() - t0;
        if (!res.ok || ms > SLOW_MS) keep(log.requests, { t: stamp(), method: method, path: path, status: res.status, ms: ms }, LIMIT.requests);
        return res;
      }, function (err) {
        keep(log.requests, { t: stamp(), method: method, path: path, status: 0, ms: Date.now() - t0, error: short(err && err.message || err, 200) }, LIMIT.requests);
        throw err;
      });
    };
  }

  /**
   * The screen as it changes: the page's size, 100dvh, the zoom, the orientation and the scroll position, written
   * down on opening, on every resize, rotation and click, but only when something differs from the last entry.
   */
  var dvh = null;
  function sizes(why) {
    try {
      if (!dvh && document.body) {
        dvh = document.createElement("div");
        dvh.setAttribute("aria-hidden", "true");
        dvh.style.cssText = "position:fixed;top:0;left:0;width:0;height:100dvh;visibility:hidden;pointer-events:none";
        document.body.appendChild(dvh);
      }
      var vv = window.visualViewport;
      var s = {
        viewport: window.innerWidth + "×" + window.innerHeight,
        dvh: dvh ? dvh.offsetHeight : null,
        zoom: vv ? Math.round(vv.width) + "×" + Math.round(vv.height) + " ×" + Math.round(vv.scale * 100) / 100 : "",
        orientation: (screen.orientation && screen.orientation.type) || "",
        scrollY: Math.round(window.scrollY),
      };
      var last = log.sizes[log.sizes.length - 1];
      if (last && ["viewport", "dvh", "zoom", "orientation", "scrollY"].every(function (k) { return last[k] === s[k]; })) return;
      keep(log.sizes, { t: stamp(), why: why, viewport: s.viewport, dvh: s.dvh, zoom: s.zoom, orientation: s.orientation, scrollY: s.scrollY }, LIMIT.sizes);
    } catch (e) {}
  }
  window.addEventListener("resize", function () { sizes("resize"); });
  if (window.visualViewport) window.visualViewport.addEventListener("resize", function () { sizes("zoom"); });
  if (screen.orientation && screen.orientation.addEventListener) screen.orientation.addEventListener("change", function () { sizes("rotate"); });
  document.addEventListener("pointerdown", function () { sizes("touch"); }, { capture: true, passive: true });
  if (document.body) sizes("open");
  else document.addEventListener("DOMContentLoaded", function () { sizes("open"); });

  function userId() {
    var el = document.querySelector("[data-report-user]");
    return el ? el.getAttribute("data-report-user") : null;
  }

  /** Everything sent with a report except its pictures. The server adds who sent it, the branch and the code version. */
  function context() {
    var mm = function (q) { try { return !!window.matchMedia(q).matches; } catch (e) { return false; } };
    var tz = "";
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) {}
    return {
      where: { path: here(), title: document.title },
      before: { taps: log.taps.slice(), pages: log.pages.slice(), errors: log.errors.slice(), requests: log.requests.slice(), sizes: log.sizes.slice() },
      device: {
        userAgent: navigator.userAgent,
        screen: screen.width + "×" + screen.height,
        viewport: window.innerWidth + "×" + window.innerHeight,
        pixelRatio: window.devicePixelRatio || 1,
        orientation: (screen.orientation && screen.orientation.type) || (window.innerWidth > window.innerHeight ? "landscape" : "portrait"),
        installed: mm("(display-mode: standalone)") || navigator.standalone === true,
        online: navigator.onLine,
        language: navigator.language,
        timeZone: tz,
        localTime: new Date().toString(),
      },
    };
  }

  /* ---------- pictures ---------- */

  var libPromise = null;
  function loadLib() {
    if (window.modernScreenshot) return Promise.resolve(window.modernScreenshot);
    if (!libPromise) {
      libPromise = new Promise(function (ok, fail) {
        var s = document.createElement("script");
        s.src = LIB_URL;
        s.onload = function () { window.modernScreenshot ? ok(window.modernScreenshot) : fail(new Error("the picture library did not start")); };
        s.onerror = function () { libPromise = null; fail(new Error("the picture library did not load")); };
        document.head.appendChild(s);
      });
    }
    return libPromise;
  }
  function withTimeout(p, ms) {
    return Promise.race([p, new Promise(function (_, fail) { setTimeout(function () { fail(new Error("it took too long")); }, ms); })]);
  }
  function bytesOf(dataUrl) { return Math.floor((dataUrl.length - dataUrl.indexOf(",") - 1) * 3 / 4); }

  /** A JPEG of at most about 300 KB: lower quality first, then a smaller picture. */
  function toJpeg(canvas) {
    var c = canvas;
    for (var round = 0; round < 4; round++) {
      for (var q = 0.8; q >= 0.35; q -= 0.15) {
        var url = c.toDataURL("image/jpeg", q);
        if (bytesOf(url) <= MAX_PICTURE) return url;
      }
      var smaller = document.createElement("canvas");
      smaller.width = Math.round(c.width * 0.7);
      smaller.height = Math.round(c.height * 0.7);
      smaller.getContext("2d").drawImage(c, 0, 0, smaller.width, smaller.height);
      c = smaller;
    }
    return c.toDataURL("image/jpeg", 0.35);
  }

  /** The visible part of the page as the user sees it, at most 1600 px on its long side, password fields left out.
      font: false -- CAS's fonts come from Google Fonts, which the page's connect-src policy keeps the library from fetching. */
  function capturePage() {
    return withTimeout(loadLib().then(function (lib) {
      var w = window.innerWidth, h = window.innerHeight;
      var scale = Math.min(window.devicePixelRatio || 1, MAX_SIDE / Math.max(w, h));
      return lib.domToCanvas(document.documentElement, {
        scale: scale,
        font: false,
        filter: function (node) {
          if (!node || node.nodeType !== 1) return true;
          if (node.classList && node.classList.contains("cas-report-back")) return false;
          return !(node.tagName === "INPUT" && node.type === "password");
        },
      }).then(function (full) {
        var out = document.createElement("canvas");
        out.width = Math.round(w * scale);
        out.height = Math.round(h * scale);
        out.getContext("2d").drawImage(full, Math.round(window.scrollX * scale), Math.round(window.scrollY * scale), out.width, out.height, 0, 0, out.width, out.height);
        return toJpeg(out);
      });
    }), 10000);
  }

  /** A screenshot the user picked, shrunk the same way. Read as a data: URL: the page's img-src policy has no blob:. */
  function shrinkFile(file) {
    return new Promise(function (ok, fail) {
      var reader = new FileReader();
      reader.onerror = function () { fail(new Error("that file could not be read")); };
      reader.onload = function () {
        var img = new Image();
        img.onload = function () {
          var k = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
          var c = document.createElement("canvas");
          c.width = Math.round(img.naturalWidth * k);
          c.height = Math.round(img.naturalHeight * k);
          c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
          ok(toJpeg(c));
        };
        img.onerror = function () { fail(new Error("that file is not a picture")); };
        img.src = reader.result;
      };
      reader.readAsDataURL(file);
    });
  }

  /* ---------- sending and the queue ---------- */

  function csrfToken() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return (m && m.getAttribute("content")) || "";
  }
  /** The token is read when sending, so a queued report carries the page it is sent from.
      redirect: "error" -- a CAS gate that redirects (signed out, branch picker) must never read as sent. */
  function send(payload) {
    return window.fetch(ENDPOINT, {
      method: "POST",
      credentials: "same-origin",
      redirect: "error",
      headers: { "content-type": "application/json", "x-csrftoken": csrfToken() },
      body: JSON.stringify(payload),
    });
  }

  var DB = "cas-reports", STORE = "pending";
  var MAX_TRIES = 5;
  var MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
  function idb() {
    return new Promise(function (ok, fail) {
      var r = window.indexedDB.open(DB, 1);
      r.onupgradeneeded = function () { r.result.createObjectStore(STORE, { autoIncrement: true }); };
      r.onsuccess = function () { ok(r.result); };
      r.onerror = function () { fail(r.error); };
    });
  }
  function queue(item) {
    return idb().then(function (db) {
      return new Promise(function (ok, fail) {
        var tx = db.transaction(STORE, "readwrite");
        tx.objectStore(STORE).add(item);
        tx.oncomplete = function () { ok(); };
        tx.onerror = function () { fail(tx.error); };
      });
    });
  }
  function drop(db, key) {
    try { db.transaction(STORE, "readwrite").objectStore(STORE).delete(key); } catch (e) {}
  }
  function requeue(db, key, value) {
    try { db.transaction(STORE, "readwrite").objectStore(STORE).put(value, key); } catch (e) {}
  }
  var flushing = null;
  /** Sends this user's waiting reports. Only one pass runs at a time; a call while one is running joins it. */
  function flush() {
    if (flushing) return flushing;
    flushing = runFlush().then(function (r) { flushing = null; return r; }, function (e) { flushing = null; throw e; });
    return flushing;
  }
  /** Kept (requeued with tries + 1) on network errors (a redirect counts as one), 5xx, 408, 429, 401 (signed out)
      and 400 bad_csrf (stale token); dropped when sent (201), refused for good by any other 4xx, too old or tried
      too many times. A network error, a 401 or a bad_csrf stops the pass; the rest stay queued untouched. */
  function runFlush() {
    var me = userId();
    if (!me || !window.indexedDB) return Promise.resolve();
    return idb().then(function (db) {
      return new Promise(function (ok) {
        var items = [];
        var req = db.transaction(STORE, "readonly").objectStore(STORE).openCursor();
        req.onsuccess = function () {
          var c = req.result;
          if (c) { items.push({ key: c.key, value: c.value }); c.continue(); } else ok({ db: db, items: items });
        };
        req.onerror = function () { ok({ db: db, items: [] }); };
      });
    }).then(function (r) {
      var chain = Promise.resolve();
      var now = Date.now();
      r.items.forEach(function (it) {
        if (!it.value || it.value.user !== me) return;
        var tries = it.value.tries || 0;
        var age = now - Date.parse(it.value.at);
        if (tries >= MAX_TRIES || (isFinite(age) && age > MAX_AGE_MS)) {
          drop(r.db, it.key);
          return;
        }
        chain = chain.then(function () {
          return send(it.value.payload).then(
            function (res) {
              var again = function () { requeue(r.db, it.key, { user: it.value.user, payload: it.value.payload, at: it.value.at, tries: tries + 1 }); };
              if (res.status === 201) { drop(r.db, it.key); return; }
              if (res.status === 401) { again(); throw new Error("signed out"); }
              if (res.status === 400) {
                return res.json().catch(function () { return {}; }).then(function (b) {
                  if (b && b.error === "bad_csrf") { again(); throw new Error("stale token"); }
                  drop(r.db, it.key);
                });
              }
              if (res.status >= 400 && res.status < 500 && res.status !== 408 && res.status !== 429) drop(r.db, it.key);
              else again();
            },
            function (err) {
              requeue(r.db, it.key, { user: it.value.user, payload: it.value.payload, at: it.value.at, tries: tries + 1 });
              throw err;
            },
          );
        });
      });
      return chain;
    }).catch(function () {});
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { flush(); });
  else setTimeout(flush, 0);
  window.addEventListener("online", function () { flush(); });

  /* ---------- the sheet ---------- */

  function h(tag, props, kids) {
    var el = document.createElement(tag);
    for (var k in props || {}) {
      if (k === "text") el.textContent = props[k];
      else if (k === "className") el.className = props[k];
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), props[k]);
      else el.setAttribute(k, props[k]);
    }
    (kids || []).forEach(function (c) { if (c) el.appendChild(c); });
    return el;
  }
  function b64(dataUrl) { return dataUrl.slice(dataUrl.indexOf(",") + 1); }

  var MESSAGES = {
    401: "You have been signed out. Sign in again, then send the report.",
    413: "The report is too large. Untick the picture and send again.",
    429: "You have sent 10 reports today. Please try again tomorrow.",
  };
  var busy = false;

  function open() {
    if (busy) return;
    busy = true;
    var back = h("div", { className: "cas-report-back" }, [h("p", { className: "cas-report-wait", text: "Taking a picture of the page…" })]);
    document.body.appendChild(back);
    var ctx = context();
    capturePage().then(function (url) { show(back, ctx, url, ""); }, function (e) { show(back, ctx, null, short(e && e.message || e, 120)); });
  }

  function show(back, ctx, picture, pictureError) {
    var own = null;
    function close() { back.remove(); busy = false; }
    var message = h("textarea", { name: "message", maxlength: "5000", required: "required", rows: "5" });
    var status = h("p", { className: "cas-report-status", role: "status" });
    var usePicture = h("input", { type: "checkbox", checked: "checked" });
    var ownPreview = h("div", { className: "cas-report-own" });
    var file = h("input", { type: "file", accept: "image/*", hidden: "hidden" });
    file.addEventListener("change", function () {
      if (!file.files || !file.files[0]) return;
      shrinkFile(file.files[0]).then(function (url) {
        own = url;
        ownPreview.textContent = "";
        ownPreview.appendChild(h("img", { src: url, alt: "Your screenshot", className: "cas-report-shot" }));
        ownPreview.appendChild(h("button", { type: "button", className: "btn btn-secondary", text: "Remove your screenshot", onclick: function () { own = null; ownPreview.textContent = ""; } }));
      }, function (e) { status.className = "cas-report-status bad"; status.textContent = e.message; });
    });
    var pictureBlock = picture
      ? h("div", { className: "cas-report-picture" }, [
          h("img", { src: picture, alt: "Picture of the page", className: "cas-report-shot", title: "Click to see it full size", onclick: function (e) { e.currentTarget.classList.toggle("big"); } }),
          h("label", { className: "cas-report-check" }, [usePicture, document.createTextNode("Include this picture of the page")]),
        ])
      : h("p", { className: "cas-report-muted", text: "The page picture could not be taken (" + pictureError + "). You can add your own screenshot." });
    var sendButton = h("button", { type: "submit", className: "btn btn-primary", text: "Send" });
    var form = h("form", { className: "cas-report-sheet", "aria-label": "Report a problem" }, [
      h("h2", { text: "Report a problem" }),
      h("p", { text: "Tell us what went wrong. The details below go with it, so you don't need to describe the page." }),
      h("label", { className: "cas-report-field" }, [document.createTextNode("What happened?"), message]),
      pictureBlock,
      h("div", null, [h("button", { type: "button", className: "btn btn-secondary", text: "Add your own screenshot", onclick: function () { file.click(); } }), file, ownPreview]),
      h("details", null, [h("summary", { text: "What we'll send" }), h("pre", { text: JSON.stringify(ctx, null, 2) })]),
      status,
      h("div", { className: "cas-report-actions" }, [h("button", { type: "button", className: "btn btn-secondary", text: "Cancel", onclick: close }), sendButton]),
    ]);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var text = message.value.trim();
      if (!text) { status.className = "cas-report-status bad"; status.textContent = "Write what happened first."; return; }
      var images = [];
      if (picture && usePicture.checked) images.push({ kind: "page", mime: "image/jpeg", data: b64(picture) });
      if (own) images.push({ kind: "own", mime: "image/jpeg", data: b64(own) });
      var payload = { message: text, context: ctx, images: images };
      sendButton.disabled = true;
      status.className = "cas-report-status";
      status.textContent = "Sending…";
      /* Only a 201 is sent. A network error, a redirect (fetch rejects), a 5xx or a stale CSRF token waits in the queue. */
      send(payload).then(function (res) {
        if (res.status === 201) {
          status.textContent = "Sent. Thank you!";
          setTimeout(close, 1200);
          return;
        }
        if (res.status >= 500) return saveForLater();
        return res.json().catch(function () { return {}; }).then(function (b) {
          if (res.status === 400 && b.error === "bad_csrf") return saveForLater();
          status.className = "cas-report-status bad";
          status.textContent = MESSAGES[res.status] || "Could not send: " + (b.error || res.status) + ".";
          sendButton.disabled = false;
        });
      }, saveForLater);
      function saveForLater() {
        return queue({ user: userId(), payload: payload, at: stamp(), tries: 0 }).then(function () {
          status.textContent = "No connection. The report is saved in this browser and will be sent the next time you open a CAS page.";
          setTimeout(close, 2500);
        }, function () {
          status.className = "cas-report-status bad";
          status.textContent = "Could not send or save the report. Please try again.";
          sendButton.disabled = false;
        });
      }
    });
    back.textContent = "";
    back.appendChild(form);
    message.focus();
  }

  /* The topbar button (base.html) carries data-report-open. */
  document.addEventListener("click", function (e) {
    var t = e.target && e.target.closest ? e.target.closest("[data-report-open]") : null;
    if (t) { e.preventDefault(); open(); }
  });

  window.CasReport = { open: open, _log: log, _context: context, _describe: describe };
})();
