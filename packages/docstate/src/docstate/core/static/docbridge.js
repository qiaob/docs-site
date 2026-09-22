/* docbridge.js — injected into every published document by the server.
 *
 * The document runs inside a CSP-sandboxed iframe (opaque origin): it cannot read
 * the reader's cookies or call the site's API. Everything goes through
 * postMessage to the shell page, which holds the session:
 *
 *   DocState.get(key, {scope})          -> Promise<value|null>   scope: "me" | "shared"
 *   DocState.set(key, value, {scope})   -> Promise<value>
 *   DocState.subscribe(key, fn, {scope, interval}) -> unsubscribe()
 *   DocState.viewer()                   -> reader email (after ready)
 *   DocState.ready                      -> Promise resolved when the shell answered
 *   DocState.inShell                    -> false when the raw page is opened directly
 *
 * Opened outside the shell (no parent frame) it degrades to per-tab memory (the
 * sandbox forbids localStorage), so a document never breaks — it just forgets.
 * Also reports its height so the iframe never needs its own scrollbar, and routes
 * clicks on /d/... links to the shell (a sandboxed frame cannot navigate its parent).
 */
(function () {
  "use strict";
  var inShell = false;
  try { inShell = window.parent && window.parent !== window; } catch (e) { inShell = false; }

  var seq = 0, pending = {}, ctx = null, resolveReady;
  var ready = new Promise(function (r) { resolveReady = r; });
  var memory = {};

  function post(msg) {
    msg.__docbridge = 1;
    window.parent.postMessage(msg, "*");
  }
  function call(type, payload) {
    return new Promise(function (resolve, reject) {
      var id = ++seq;
      pending[id] = { resolve: resolve, reject: reject };
      post({ type: type, id: id, payload: payload });
      setTimeout(function () {
        if (pending[id]) { delete pending[id]; reject(new Error("docbridge: shell did not answer")); }
      }, 8000);
    });
  }

  window.addEventListener("message", function (ev) {
    var d = ev.data;
    if (!d || d.__docbridge !== 1) return;
    if (d.type === "reply" && pending[d.id]) {
      var p = pending[d.id]; delete pending[d.id];
      d.error ? p.reject(new Error(d.error)) : p.resolve(d.result);
    } else if (d.type === "ctx") {
      ctx = d.payload || {};
      resolveReady(ctx);
    } else if (d.type === "remeasure") {
      // the shell changed our width (wide mode); height follows from it
      lastH = 0;
      setTimeout(report, 0);
      scheduleToc();
    }
  });

  function memKey(key, scope) { return scope + ":" + key; }

  var DocState = {
    inShell: inShell,
    ready: ready,
    viewer: function () { return ctx ? ctx.viewer : null; },
    get: function (key, opts) {
      var scope = (opts && opts.scope) || "me";
      if (!inShell) return Promise.resolve(memory.hasOwnProperty(memKey(key, scope)) ? memory[memKey(key, scope)] : null);
      return call("state.get", { key: key, scope: scope });
    },
    set: function (key, value, opts) {
      var scope = (opts && opts.scope) || "me";
      if (!inShell) { memory[memKey(key, scope)] = value; return Promise.resolve(value); }
      return call("state.set", { key: key, scope: scope, value: value });
    },
    subscribe: function (key, fn, opts) {
      var scope = (opts && opts.scope) || "shared";
      var interval = (opts && opts.interval) || 4000;
      var last;
      var tick = function () {
        DocState.get(key, { scope: scope }).then(function (v) {
          var s = JSON.stringify(v);
          if (s !== last) { last = s; fn(v); }
        }).catch(function () {});
      };
      tick();
      var timer = setInterval(tick, interval);
      return function () { clearInterval(timer); };
    }
  };
  window.DocState = DocState;

  if (!inShell) { resolveReady({ viewer: null, standalone: true }); return; }

  // --- height reporting (no inner scrollbar) ---
  // Measure the CONTENT, never the viewport: documentElement.scrollHeight is
  // clamped to the viewport, and the shell resizes the viewport to what we
  // report, which would feed back into an ever-growing frame.
  var lastH = 0;
  function contentHeight() {
    var b = document.body, de = document.documentElement;
    if (!b) return de ? de.scrollHeight : 0;
    var cs = window.getComputedStyle(b);
    var mt = parseFloat(cs.marginTop) || 0, mb = parseFloat(cs.marginBottom) || 0;
    return Math.ceil(Math.max(b.scrollHeight, b.offsetHeight) + mt + mb);
  }
  function report() {
    var h = contentHeight();
    if (h && Math.abs(h - lastH) > 4) { lastH = h; post({ type: "height", height: h }); scheduleToc(); }
  }

  // --- document outline for the shell's right rail ---
  // Headings (h1 under h2/h3 only when there are several) with their offsets;
  // headings without an id get one so links stay addressable.
  var tocTimer = null, lastToc = "";
  function slug(text) {
    return String(text).toLowerCase().replace(/[^\w一-鿿]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "h";
  }
  function collectToc() {
    var hs = Array.prototype.slice.call(document.querySelectorAll("h1, h2, h3"));
    var h1s = hs.filter(function (h) { return h.tagName === "H1"; });
    if (h1s.length <= 1) hs = hs.filter(function (h) { return h.tagName !== "H1"; });
    var seen = {}, items = [];
    hs.forEach(function (h, i) {
      var text = (h.textContent || "").trim();
      if (!text) return;
      if (!h.id) { var base = slug(text), id = base, n = 2; while (document.getElementById(id) || seen[id]) { id = base + "-" + n++; } h.id = id; }
      seen[h.id] = true;
      items.push({ level: +h.tagName[1], text: text.slice(0, 80), id: h.id, top: Math.round(h.getBoundingClientRect().top + window.scrollY) });
    });
    return items;
  }
  function sendToc() {
    var items = collectToc(), s = JSON.stringify(items);
    if (s !== lastToc) { lastToc = s; post({ type: "toc", items: items }); }
  }
  function scheduleToc() { clearTimeout(tocTimer); tocTimer = setTimeout(sendToc, 150); }
  window.addEventListener("load", scheduleToc);
  if (document.readyState !== "loading") scheduleToc(); else document.addEventListener("DOMContentLoaded", scheduleToc);
  window.addEventListener("load", report);
  window.addEventListener("resize", report);
  if (window.ResizeObserver) {
    var ro = new ResizeObserver(report);
    ro.observe(document.documentElement);
    if (document.body) ro.observe(document.body); else document.addEventListener("DOMContentLoaded", function () { ro.observe(document.body); });
  }
  if (window.MutationObserver) {
    new MutationObserver(function () { setTimeout(report, 0); }).observe(document.documentElement, { childList: true, subtree: true, attributes: true, characterData: true });
  }
  var burst = 0, burstTimer = setInterval(function () { report(); if (++burst > 10) clearInterval(burstTimer); }, 500);

  // --- wheel relay ---
  // The first wheel event of a gesture lands here (the pointer is over us). Tell
  // the shell, which then routes the rest of the gesture past this frame so the
  // scroll stays on the parent's compositor instead of bouncing through this
  // out-of-process frame on every tick.
  var lastWheel = 0;
  window.addEventListener("wheel", function () {
    var now = Date.now();
    if (now - lastWheel > 60) { lastWheel = now; post({ type: "wheel" }); }
  }, { passive: true });

  // --- internal links go to the shell ---
  document.addEventListener("click", function (e) {
    var a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
    if (!a) return;
    var href = a.getAttribute("href") || "";
    // a link written as a full URL to this very site is still an internal link:
    // followed inside the sandboxed frame it would land on the login front door
    var base = (ctx && ctx.base) || "";
    if (base && href.indexOf(base) === 0) href = href.slice(base.length) || "/";
    if (href.charAt(0) === "#") return;                       // in-page anchor: scroll here
    if (/^(mailto|tel):/i.test(href)) return;                 // handled by the OS
    if (href.indexOf("/d/") === 0 || href.indexOf("/c/") === 0 || href === "/" || href.indexOf("/t") === 0) {
      e.preventDefault();
      post({ type: "navigate", href: href });                 // the shell navigates, not this frame
    } else if (!a.target) {
      // Anything else leaves the site. Opening it inside the frame would
      // replace the document the reader is on (and, for our own origin, land
      // on the login front door), so it goes to a new browser tab.
      a.target = "_blank"; a.rel = "noopener noreferrer";
    }
  });

  // Announce until the shell answers with ctx (the shell's listener may attach a beat later).
  var hello = 0, helloTimer = setInterval(function () {
    if (ctx || ++hello > 8) { clearInterval(helloTimer); return; }
    post({ type: "ready" });
  }, 400);
  post({ type: "ready" });
})();
