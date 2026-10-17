"use strict";
/* Shared by every page: the nav and footer, the API helper, the account control and its
   sign-in dialog, and the small renderers (crest medallion, rating chip, team colours,
   the dealt squad, the pitch) that make the pages one site. */

const SITE_NAME = "UCLnights11";
// The logo the user supplied, cut out by tools.build_brand.
const SITE_LOGO = "/static/brand/logo.webp";
// The emblem alone, for a phone's nav, where the whole logo leaves no room for the links.
const SITE_EMBLEM = "/static/brand/emblem.webp";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function shell(active) {
  const nav = document.createElement("header");
  nav.className = "topnav";
  nav.innerHTML = `<div class="topnav-in">
    <a class="brand" href="/" aria-label="${esc(SITE_NAME)} home"><picture>
      <source media="(max-width: 480px)" srcset="${SITE_EMBLEM}">
      <img src="${SITE_LOGO}" alt="${esc(SITE_NAME)}" width="129" height="32"></picture></a>
    <nav class="navlinks">
      <a href="/start" ${active === "draft" ? 'class="on"' : ""}>Draft</a>
      <a href="/daily" ${active === "daily" ? 'class="on"' : ""}>Daily</a>
      <a href="/friends" ${active === "friends" ? 'class="on"' : ""}>Friends</a>
      <a href="/archive" ${active === "archive" ? 'class="on"' : ""}>Archive</a>
    </nav>
    <div class="nav-r"><span class="nav-stat" id="navstat"></span><span class="nav-acct" id="navacct"></span></div></div>`;
  document.body.prepend(nav);
  const foot = document.createElement("footer");
  foot.className = "foot";
  foot.innerHTML = `<div class="foot-in"><div class="foot-brand"><img src="${SITE_EMBLEM}" alt="" width="40" height="40">
    <div><p>Squads from Wikipedia (CC BY-SA). Club crests belong to their clubs and appear here on a
    non-commercial fan site. Ratings are this game's own judgement, as are positions before 2013–14; later
    positions come from Transfermarkt's line-ups via transfermarkt-datasets (CC0). Real results for the match
    engine come from openfootball (CC0).</p><p>An independent fan game, not affiliated with UEFA or any club.</p></div></div>
    <nav class="foot-links" aria-label="About the site"><a href="/about">About</a><a href="/faq">FAQ</a>
      <a href="/privacy">Privacy</a><a href="/terms">Terms</a></nav></div>`;
  document.body.append(foot);
  const t = document.createElement("div");
  t.className = "toast"; t.id = "toast"; t.setAttribute("role", "status");
  document.body.append(t);
  lens();
  loadMe();
  installable();
}

/* Liquid glass (C58). Every floating layer is frosted glass in the stylesheet; in Chromium,
   the one engine that takes an SVG filter as a backdrop, the small ones that stay put also
   bend the light at their edges, through this displacement map. Not under the nav or
   anything else that floats over scrolling content: re-running a filter there every frame
   is what makes scrolling stutter on a phone. */
function lens() {
  const chromium = navigator.userAgentData && navigator.userAgentData.brands.some((b) => /Chromium/.test(b.brand));
  if (!chromium || matchMedia("(prefers-reduced-transparency: reduce)").matches) return;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("style", "position:absolute;width:0;height:0");
  svg.innerHTML = `<filter id="lg-lens" x="0%" y="0%" width="100%" height="100%" color-interpolation-filters="sRGB">
    <feImage href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100' preserveAspectRatio='none'%3E%3ClinearGradient id='a' x2='1' y2='0'%3E%3Cstop offset='0' stop-color='rgb(255,0,0)'/%3E%3Cstop offset='0.07' stop-color='rgb(128,0,0)'/%3E%3Cstop offset='0.93' stop-color='rgb(128,0,0)'/%3E%3Cstop offset='1' stop-color='rgb(0,0,0)'/%3E%3C/linearGradient%3E%3Crect width='100' height='100' fill='url(%23a)'/%3E%3C/svg%3E" preserveAspectRatio="none" x="0%" y="0%" width="100%" height="100%" result="r"/>
    <feImage href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100' preserveAspectRatio='none'%3E%3ClinearGradient id='a' x2='0' y2='1'%3E%3Cstop offset='0' stop-color='rgb(0,255,0)'/%3E%3Cstop offset='0.22' stop-color='rgb(0,128,0)'/%3E%3Cstop offset='0.78' stop-color='rgb(0,128,0)'/%3E%3Cstop offset='1' stop-color='rgb(0,0,0)'/%3E%3C/linearGradient%3E%3Crect width='100' height='100' fill='url(%23a)'/%3E%3C/svg%3E" preserveAspectRatio="none" x="0%" y="0%" width="100%" height="100%" result="g"/>
    <feComposite in="r" in2="g" operator="arithmetic" k2="1" k3="1" result="map"/>
    <feDisplacementMap in="SourceGraphic" in2="map" scale="26" xChannelSelector="R" yChannelSelector="G"/></filter>`;
  document.body.append(svg);
  document.documentElement.classList.add("lens");
}

/* Installing the site as an app (sw.js, manifest.webmanifest). Not on a local server,
   where a worker caching scripts would hide edits from whoever is making them. */
let INSTALL = null;
function installable() {
  const local = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
  if ("serviceWorker" in navigator && !local) navigator.serviceWorker.register("/sw.js").catch(() => {});
  const link = document.createElement("a");
  link.href = "#"; link.id = "install"; link.hidden = true; link.textContent = "Install app";
  link.onclick = async (e) => {
    e.preventDefault();
    if (!INSTALL) return;
    INSTALL.prompt();
    await INSTALL.userChoice.catch(() => {});
    INSTALL = null; link.hidden = true;
  };
  document.querySelector(".foot-links")?.append(link);
}
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();                                  // offered from the footer, never popped up
  INSTALL = e;
  const link = $("install");
  if (link) link.hidden = false;
});
window.addEventListener("appinstalled", () => { INSTALL = null; const l = $("install"); if (l) l.hidden = true; });

/* Every call to the API. A thrown error carries `status`: the HTTP status, or 0 when no
   reply came at all (offline, a phone that froze the tab, a timeout). A read is retried
   once on 0 or a gateway error, as the cricket site does (its A169); a write never is,
   because it may have landed even though the reply was lost. `opts.timeout` shortens the
   wait for a call that is asked again soon anyway (a room poll). */
const API_TIMEOUT_MS = 15000;
const RETRY_STATUS = new Set([0, 502, 503, 504]);

class ApiError extends Error {
  constructor(message, status, body = null) { super(message); this.status = status; this.body = body; }
}

async function api(path, opts = {}) {
  const read = !opts.method || opts.method === "GET";
  try {
    return await apiOnce(path, opts);
  } catch (e) {
    if (!read || !RETRY_STATUS.has(e.status)) throw e;
    await new Promise((r) => setTimeout(r, 700));
    return apiOnce(path, opts);
  }
}

async function apiOnce(path, opts) {
  const { timeout = API_TIMEOUT_MS, ...init } = opts;
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  const call = `${init.method || "GET"} ${routeOf(path)}`;
  let res;
  try {
    res = await fetch(path, { headers: { "Content-Type": "application/json" }, signal: ctl.signal, ...init });
  } catch (e) {
    const offline = navigator.onLine === false;
    // No reply at all is reported too, or a timeout leaves no trace anywhere. Not when
    // the browser knows it is offline, the tab is hidden (a phone freezing it) or the
    // page is being left (which cancels whatever is in flight).
    if (!offline && !LEAVING && document.visibilityState === "visible") {
      reportFailure("api", `${call} ${ctl.signal.aborted ? `timeout ${timeout / 1000}s` : "no reply"}`);
    }
    throw new ApiError(offline ? "You're offline" : "Couldn't reach the server", 0);
  } finally { clearTimeout(timer); }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new ApiError(body.detail || `Request failed (${res.status})`, res.status, body);
    if (res.status >= 500) reportFailure("api", `${call} ${res.status}`);
    throw err;
  }
  return body;
}

let LEAVING = false;
window.addEventListener("pagehide", () => { LEAVING = true; });
window.addEventListener("pageshow", () => { LEAVING = false; });   // back from the cache

/* A path as one row in the failure reports however many drafts or rooms hit it: the
   draft state or room code is replaced, /api/rooms/AB12CD -> /api/rooms/:id. */
function routeOf(path) {
  return path.split("?")[0].replace(/^\/api\/(draft|tournament|rooms|squad)\/[^/]+/, "/api/$1/:id");
}

/* Failures this browser saw, sent to /api/client-failures so a broken page is noticed
   without anyone having to report it (the cricket site's A180). A few per page, never the
   same one twice, and never anything that identifies the person. */
const reported = new Set();
function reportFailure(kind, detail) {
  const key = `${kind}:${detail}`;
  if (reported.has(key) || reported.size >= 5) return;
  reported.add(key);
  const body = JSON.stringify({ kind, detail: String(detail).slice(0, 500), page: location.pathname });
  try {
    if (navigator.sendBeacon) navigator.sendBeacon("/api/client-failures", new Blob([body], { type: "application/json" }));
    else fetch("/api/client-failures", { method: "POST", body, headers: { "Content-Type": "application/json" }, keepalive: true });
  } catch { /* reporting must never break the page */ }
}
window.addEventListener("error", (e) => reportFailure("error", `${e.message} @ ${(e.filename || "").split("/").pop()}:${e.lineno}`));
window.addEventListener("unhandledrejection", (e) => {
  if (e.reason instanceof ApiError) return;           // the request itself was reported, or it was the network
  if (skippedTransition(e.reason)) { e.preventDefault(); return; }
  reportFailure("rejection", e.reason && e.reason.message || String(e.reason));
});

/* --- the account: who is signed in, and the dialog that signs them in --- */

let ME;                       // undefined until asked, then null or {id, username}
const authListeners = [];

function loadMe() {
  if (loadMe.p) return loadMe.p;
  loadMe.p = api("/api/auth/me").then((r) => r.account, () => null).then((a) => { setMe(a); return a; });
  return loadMe.p;
}

function setMe(account) {
  ME = account;
  const el = $("navacct");
  if (el) {
    // Signed in, the control is one button that opens a small menu: a username and a
    // "Sign out" side by side pushed the nav off the side of a phone.
    el.innerHTML = ME
      ? `<button class="acct-btn" id="acctb" aria-haspopup="menu" aria-expanded="false" title="Signed in as ${esc(ME.username)}">
           <span class="acct-init" aria-hidden="true">${esc(ME.username[0].toUpperCase())}</span><span class="who-me">${esc(ME.username)}</span></button>
         <div class="acct-menu" id="acctm" role="menu" hidden>
           <div class="acct-who">Signed in as <b>${esc(ME.username)}</b></div>
           <a role="menuitem" href="/profile">Profile</a>
           ${ME.admin ? `<a role="menuitem" href="/admin">Admin</a>` : ""}
           <button role="menuitem" id="signout">Sign out</button></div>`
      : `<button class="btn small ghost" id="signin">Sign in</button>`;
    const out = $("signout"), inn = $("signin"), btn = $("acctb");
    if (out) out.onclick = async () => { await api("/api/auth/logout", { method: "POST" }).catch(() => {}); setMe(null); };
    if (inn) inn.onclick = () => openAuth();
    if (btn) btn.onclick = (e) => { e.stopPropagation(); toggleAcct(); };
  }
  authListeners.forEach((f) => f(ME));
}

function toggleAcct(open) {
  const m = $("acctm"), b = $("acctb");
  if (!m) return;
  const show = open ?? m.hidden;
  m.hidden = !show;
  b.setAttribute("aria-expanded", show);
}
document.addEventListener("click", (e) => { if (!e.target.closest(".nav-acct")) toggleAcct(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") toggleAcct(false); });

function onAuth(f) { authListeners.push(f); if (ME !== undefined) f(ME); }

function openAuth(mode = "in", why = "") {
  closeAuth();
  const box = document.createElement("div");
  box.className = "modal"; box.id = "authmodal";
  box.innerHTML = `<div class="modal-in" role="dialog" aria-modal="true" aria-labelledby="authh">
    <button class="close" id="authx" aria-label="Close">✕</button>
    <div class="tabs" role="tablist">
      <button role="tab" data-m="in">Sign in</button><button role="tab" data-m="up">Create account</button></div>
    <h2 id="authh"></h2>${why ? `<p class="why-sign">${esc(why)}</p>` : ""}
    <form id="authform" novalidate>
      <label data-only="up">Username<input name="username" autocomplete="username" maxlength="20" placeholder="3-20 letters, numbers or _"></label>
      <label data-only="in">Username or email<input name="identifier" autocomplete="username"></label>
      <label data-only="up">Email<input name="email" type="email" autocomplete="email"></label>
      <label>Password<input name="password" type="password" minlength="8"></label>
      <p class="form-err" id="autherr" role="alert"></p>
      <button class="btn primary" type="submit" id="authgo"></button>
    </form></div>`;
  document.body.append(box);
  const form = $("authform");
  const set = (m) => {
    mode = m;
    box.querySelectorAll("[role=tab]").forEach((b) => b.setAttribute("aria-selected", b.dataset.m === m));
    box.querySelectorAll("[data-only]").forEach((l) => l.hidden = l.dataset.only !== m);
    $("authh").textContent = m === "in" ? "Welcome back" : "Join the nights";
    $("authgo").textContent = m === "in" ? "Sign in" : "Create account";
    form.password.autocomplete = m === "in" ? "current-password" : "new-password";
    $("autherr").textContent = "";
    (m === "in" ? form.identifier : form.username).focus();
  };
  box.querySelectorAll("[role=tab]").forEach((b) => b.onclick = () => set(b.dataset.m));
  $("authx").onclick = closeAuth;
  box.onclick = (e) => { if (e.target === box) closeAuth(); };
  box.onkeydown = (e) => { if (e.key === "Escape") closeAuth(); };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const f = form.elements, go = $("authgo");
    const body = mode === "in"
      ? { identifier: f.identifier.value, password: f.password.value }
      : { username: f.username.value, email: f.email.value, password: f.password.value };
    go.disabled = true;
    try {
      const r = await api(`/api/auth/${mode === "in" ? "login" : "register"}`, { method: "POST", body: JSON.stringify(body) });
      closeAuth();
      setMe(r.account);
      toast(mode === "in" ? `Signed in as ${r.account.username}` : `Welcome, ${r.account.username}`);
    } catch (err) { $("autherr").textContent = err.message; } finally { go.disabled = false; }
  };
  set(mode);
}

function closeAuth() { const m = $("authmodal"); if (m) m.remove(); }

/* Copy a link, or hand it to the phone's share sheet where there is one. The text itself
   is the last resort, shown where it can be copied by hand. */
function copyText(text, done = "Copied") {
  if (navigator.share && matchMedia("(pointer: coarse)").matches) {
    navigator.share({ url: text }).catch(() => {});
    return;
  }
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject())
    .then(() => toast(done), () => toast(text));
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), 2600);
}

let META = null;
async function loadMeta() {
  if (!META) {
    META = await api("/api/meta");
    const s = $("navstat");
    if (s) s.textContent = `${META.club_seasons} squads · ${META.first_season.slice(0, 4)}–${META.last_season.slice(5)}`;
  }
  return META;
}

/* The light medallion every crest sits on. size is one of 18/22/28/36/48/64/84/104. */
function crest(url, size = 36, alt = "") {
  if (!url) return `<span class="crest you c${size}" aria-label="Your XI">✦</span>`;
  return `<span class="crest c${size}"><img src="${url}" alt="${esc(alt)}" loading="lazy" decoding="async"></span>`;
}

/* A side's medallion: its crest, or for a friend's eleven their initial in their colours. */
function sideCrest(s, size = 36) {
  if (!s.human) return crest(s.crest, size, s.name);
  return `<span class="crest mono c${size}" style="${teamStyle(s)};--s:${size}px" aria-label="${esc(s.name)}">${esc((s.name || "?")[0].toUpperCase())}</span>`;
}

function rate(r) {
  const cls = r >= 90 ? "r90" : r >= 85 ? "r85" : r >= 80 ? "r80" : "";
  return `<span class="rate ${cls}">${r}</span>`;
}

/* Team colours as inline custom properties: the stylesheet does the rest. */
function teamStyle(x) {
  return `--team:${x.team};--team-deep:${x.deep};--team-ink:${x.ink}`;
}

/* A club-season's era, by the year its season began: a texture on its band and a mark above
   its season. Decoration only, and claims nothing about the side. */
const ERAS = [[2020, "e20", "’20s"], [2010, "e10", "’10s"], [2000, "e00", "’00s"], [0, "e90", "’90s"]];
function eraOf(x) {
  const e = x && x.year ? ERAS.find(([from]) => x.year >= from) : null;
  return e ? { cls: e[1], mark: `<span class="era-mark">${e[2]}</span>` } : { cls: "", mark: "" };
}

/* A dealt squad, by line, with a Take button on every player who fits. Shared by the
   solo draft and a room's draft; `opts` carries what differs between them. */
const LINES = { GK: "Goalkeepers", DF: "Defenders", MF: "Midfielders", FW: "Forwards" };
// Each position's line (game.positions.LINE), for colouring a position chip.
const LINE_OF = { GK: "GK", RB: "DF", CB: "DF", LB: "DF", DM: "MF", CM: "MF", AM: "MF",
  RM: "MF", LM: "MF", RW: "FW", ST: "FW", LW: "FW" };

/* A player's positions: the one he played most as a chip, the rest beside it (C35). */
function posChip(p) { return `<span class="pos ${LINE_OF[p] || p}">${p}</span>`; }
function positionsHtml(c) {
  const ps = c.positions && c.positions.length ? c.positions : [c.pos];
  return posChip(ps[0]);
}
function altPositions(c) {
  return c.positions && c.positions.length > 1 ? `<span class="alts">${c.positions.slice(1).join(" · ")}</span>` : "";
}

function renderDeal(el, d, opts) {
  // In Memory mode the API sends no ratings and lists each line by name (session_out);
  // a card's `i` is its place in the deal, which is what a pick names, whatever the order.
  const byLine = { GK: [], DF: [], MF: [], FW: [] };
  d.cards.forEach((c, k) => byLine[c.pos].push([c, c.i ?? k]));
  const open = d.cards.filter((c) => c.takeable).length;
  const rows = Object.entries(byLine).filter(([, cs]) => cs.length).map(([pos, cs]) =>
    `<div class="line-h">${LINES[pos]}</div>` + cs.map(([c, i]) => `
      <div class="row ${c.takeable ? "" : "off"}">
        ${positionsHtml(c)}
        <div class="who"><b>${esc(c.name)}</b><small>${altPositions(c)}${esc(c.nation || "")}</small></div>
        ${c.rating == null ? "" : rate(c.rating)}
        ${opts.readOnly ? (c.takeable ? "" : `<span class="why">${whyHtml(c.reason)}</span>`)
          : c.takeable ? `<button class="take" data-i="${i}" aria-label="${opts.takeLabel || "Take"} ${esc(c.name)}">${opts.takeLabel || "Take"}</button>`
                     : `<span class="why">${whyHtml(c.reason)}</span>`}
      </div>`).join("")).join("");
  el.style.cssText = teamStyle(d);
  const era = eraOf(d);
  el.innerHTML = `
    <div class="panel-h"><span class="label">${opts.headingHtml || esc(opts.heading || "Dealt to you")}</span><span class="label"><b>${open}</b> of ${d.cards.length} available</span></div>
    <div class="band ${era.cls}">
      ${crest(d.crest, 104, d.name)}
      ${era.mark}<div class="deal-year">${esc(d.season)}</div>
      <div class="deal-club">${esc(d.name)}</div>
      ${opts.onReroll ? `<div class="deal-actions">
        <button class="btn small" data-reroll ${opts.rerollsLeft ? "" : "disabled"}>Another squad</button>
        <span class="label">${opts.rerollsLeft} left</span>
      </div>` : ""}
    </div>
    <div>${rows}</div>`;
  if (opts.fresh) {
    el.classList.remove("flip"); void el.offsetWidth; el.classList.add("flip");
    // After a pick far down a long squad, the next squad starts above the screen; on a
    // phone that looked like nothing had happened.
    // Where the page is going is kept, so a pick in flight can aim at where his place will be.
    SCROLL_DEST = null;
    if (el.getBoundingClientRect().top < 0) {
      const to = document.querySelector(".draft-top") || el;
      SCROLL_DEST = Math.max(0, Math.min(to.getBoundingClientRect().top + scrollY - (parseFloat(getComputedStyle(to).scrollMarginTop) || 0),
        document.documentElement.scrollHeight - innerHeight));
      scrollTo({ top: SCROLL_DEST, behavior: "smooth" });
    }
  }
  const byI = new Map(d.cards.map((c, k) => [c.i ?? k, c]));
  el.querySelectorAll(".take").forEach((b) => b.onclick = () => {
    takeoff(b.closest(".row"), byI.get(+b.dataset.i));
    opts.onTake(+b.dataset.i);
  });
  if (opts.onReroll) el.querySelector("[data-reroll]").onclick = opts.onReroll;
}

/* Why a man can't be taken. A formation's name ("4-3-3") breaks at its hyphens, and in
   a narrow column the last digit went onto a line of its own. */
function whyHtml(reason) {
  return esc(reason).replace(/\d(?:-\d)+/g, (f) => `<span class="nw">${f}</span>`);
}

/* Which of the formation's places are filled, for the bar above the deal: on a phone the
   pitch is below the squad, so this is what tells you the right-back is already taken.
   `xi` is the picks as placed (each with its `slot`); places are listed as the formation
   lists them, a position held twice (CB, CM, ST) once with its count. */
function lineChips(el, formation, xi) {
  const need = {};
  formation.slots.forEach((s) => { need[s] = (need[s] || 0) + 1; });
  el.innerHTML = Object.entries(need).map(([s, n]) => {
    const have = xi.filter((c) => c.slot === s).length;
    return `<span class="linechip ${have >= n ? "full" : ""}">${posChip(s)}${n > 1 ? `${have}/${n}` : have ? "✓" : ""}</span>`;
  }).join("");
}

/* The numbers under a drafting eleven. A Memory draft has no ratings to average. */
function xiFoot(el, d) {
  const avg = d.memory ? "?" : d.picks.length ? Math.round(d.picks.reduce((a, c) => a + c.rating, 0) / d.picks.length) : "–";
  el.innerHTML = `<div><b>${avg}</b>${d.memory ? "Memory" : "Average"}</div><div><b>${new Set(d.picks.map((c) => c.club)).size}</b>Clubs</div><div><b>${d.rerolls_left}</b>Rerolls left</div>`;
}

/* The bench under a pitch (C40): `size` places, filled in the order they were picked. A
   substitute holds any of his positions the formation has, so his chips are all shown. */
function renderBench(el, bench, size) {
  el.hidden = !size;
  if (!size) return;
  el.innerHTML = `<div class="label">Bench</div>` + Array.from({ length: size }, (_, k) => {
    const c = bench[k];
    if (!c) return `<div class="sub-card"><span class="sub-empty">Sub ${k + 1}</span></div>`;
    return `<div class="sub-card filled" data-id="${esc(c.id)}">${crest(c.crest, 28, c.club)}
      <div class="who"><b>${esc(c.name)}</b><small>${(c.positions || [c.pos]).map(posChip).join("")}${c.rating == null ? "" : ` ${c.rating}`}</small></div></div>`;
  }).join("");
  if (FLIGHT) requestAnimationFrame(land);
}

/* A plan's conditions in words (C41), from your side's point of view; in a second leg the
   score is the aggregate. */
const WHEN_LABEL = { any: "whatever the score", behind: "if behind", level: "if level", ahead: "if ahead",
  not_ahead: "unless ahead", not_behind: "unless behind" };
const WHEN_SHORT = { ...WHEN_LABEL, any: "any score" };
const AUTO_NOTE = `Automatic: the best-rated on first, at 60', 70' and 80'. "Best change" replaces whoever it helps most to replace, and only if it helps.`;

/* A plan as the tournament page lists it: [{on, minute, when, off}] with names. */
function planHtml(plan) {
  if (!plan || !plan.length) return `<p class="plan-none">No changes planned: the eleven play every minute.</p>`;
  return `<ol class="plan-list">${[...plan].sort((a, b) => a.minute - b.minute).map((x) =>
    `<li><span class="m">${x.minute}'</span><b>${esc(x.on)}</b> <span>${esc(WHEN_LABEL[x.when])}, for ${x.off ? esc(x.off) : "whoever it helps most"}</span></li>`).join("")}</ol>`;
}

/* The plan panel (C41): for each substitute, from when, on what score and for whom. `d` is
   a finished bench draft ({bench, xi} with each bench card's `can_replace`), `plan` the
   lines to show ([{on, minute, when, off}]); `opts.tag` heads it, `opts.foot` is the
   page's own buttons, and `opts.onChange(plan)` gets the whole plan after any change.
   `opts.mode` ({ manual, onMode(manual) }, C60) offers making the changes during each
   match instead, the plan then used only where a match is skipped. */
function planPanel(el, d, plan, opts) {
  // A null plan is the automatic one, not shown: drafting blind, its order would rank the
  // substitutes (C42). Each row says "Automatic" until the drafter chooses.
  const hidden = plan == null;
  const line = (i) => hidden ? null : plan.find((x) => x.on === i);
  const opt = (v, label, on) => `<option value="${v}" ${on ? "selected" : ""}>${esc(label)}</option>`;
  el.style.cssText = "";
  el.classList.remove("flip");
  el.innerHTML = `
    <div class="panel-h"><span class="label">Your changes</span><span class="label">${esc(opts.tag || "")}</span></div>
    <div class="plan-intro"><p>Players tire as a match goes on, and a tired man defends worst. A substitute comes on fresh.
      Up to three changes, the same plan for every match. The score is the tie's: in a second leg, the aggregate.</p></div>
    ${opts.mode ? `<div class="plan-mode"><span>During matches</span><div class="chips" role="radiogroup" aria-label="Who makes the changes">
        <button class="chip" role="radio" data-manual="0" aria-checked="${!opts.mode.manual}">Follow this plan</button>
        <button class="chip" role="radio" data-manual="1" aria-checked="${!!opts.mode.manual}">I'll make them myself</button></div></div>
      <p class="plan-mode-note">${opts.mode.manual
        ? "You make the changes: <b>Make a sub</b> pauses the match, and nobody comes on unless you bring him on. The plan below is only used in a match you skip, if you say so then."
        : "The plan below makes the changes in every match. Or make them yourself: pause a match whenever you like and bring a man on."}</p>` : ""}
    ${d.bench.map((c, i) => {
      const x = line(i);
      return `<div class="plan-row" data-i="${i}">
        <div class="t">${crest(c.crest, 36, c.club)}<div class="who"><b>${esc(c.name)}</b><small>${(c.positions || [c.pos]).map(posChip).join("")}${c.rating == null ? "" : ` ${c.rating}`}</small></div></div>
        <label>On<select data-k="minute" aria-label="When ${esc(c.name)} comes on">${hidden ? opt("auto", "Automatic", true) : ""}${opt("", "Not used", !hidden && !x)}${[45, 50, 55, 60, 65, 70, 75, 80, 85].map((m) => opt(m, `from ${m}'`, x && x.minute === m)).join("")}</select></label>
        <label>When<select data-k="when" ${x ? "" : "disabled"}>${Object.entries(WHEN_SHORT).map(([k, l]) => opt(k, l, x ? x.when === k : k === "any")).join("")}</select></label>
        <label>For<select data-k="off" ${x ? "" : "disabled"}>${opt("", "best change", !x || x.off == null)}${c.can_replace.map((j) =>
          opt(j, `${d.xi[j].slot} · ${d.xi[j].name}`, x && x.off === j)).join("")}</select></label>
      </div>`;
    }).join("")}
    <div class="plan-foot">${opts.foot || ""}</div>`;
  el.querySelectorAll(".plan-row select").forEach((sel) => sel.onchange = () => opts.onChange(readPlan(el)));
  el.querySelectorAll("[data-manual]").forEach((b) => b.onclick = () => {
    if ((b.dataset.manual === "1") !== !!opts.mode.manual) opts.mode.onMode(b.dataset.manual === "1");
  });
}

/* The plan as the panel shows it. Two changes for one man can't both happen; the later
   goes back to "best change". */
function readPlan(el) {
  const seen = new Set();
  return [...el.querySelectorAll(".plan-row")].map((row) => {
    const v = (k) => row.querySelector(`[data-k="${k}"]`).value;
    if (!v("minute")) return null;
    // A row still "Automatic" once another is chosen: on at 60', 70', 80' in bench order,
    // which says nothing about ratings.
    if (v("minute") === "auto") return { on: +row.dataset.i, minute: 60 + 10 * +row.dataset.i, when: "any", off: null };
    const x = { on: +row.dataset.i, minute: +v("minute"), when: v("when"), off: v("off") === "" ? null : +v("off") };
    if (x.off != null) { if (seen.has(x.off)) x.off = null; else seen.add(x.off); }
    return x;
  }).filter(Boolean);
}

/* Where each position stands on the pitch, attacking upwards: [top %, left %] for one man;
   a position held more than once spreads across the middle by GAP. */
const SPOT = { GK: [90, 50], RB: [69, 86], CB: [73, 50], LB: [69, 14], DM: [56, 50], CM: [42, 50],
  AM: [30, 50], RM: [41, 87], LM: [41, 13], RW: [20, 82], ST: [11, 50], LW: [20, 18] };
const GAP = { CB: 25, CM: 36, DM: 24, ST: 24, AM: 30 };

function slotSpots(slots) {
  const count = {}, seen = {};
  slots.forEach((s) => { count[s] = (count[s] || 0) + 1; });
  const pivot = count.DM === 1 && count.CM === 1;   // a double pivot sits side by side
  const five = count.CB === 3 && count.RB;           // a back five: full-backs push up and out
  return slots.map((s) => {
    const k = (seen[s] = (seen[s] || 0) + 1), n = count[s];
    let [y, x] = SPOT[s];
    if (n > 1) x = 50 + (k - (n + 1) / 2) * (GAP[s] || 24);
    if (five && (s === "RB" || s === "LB")) { y = 58; x = s === "RB" ? 89 : 11; }
    if (five && s === "CB") x = 50 + (k - 2) * 22;
    if (pivot && s === "DM") { x = 38; y = 53; }
    if (pivot && s === "CM") { x = 62; y = 49; }
    return { x, y };
  });
}

function renderPitch(el, slots, xi, newest) {
  const spots = slotSpots(slots);
  const left = [...xi];
  const was = placesOf(el);
  el.innerHTML = slots.map((s, j) => {
    const at = left.findIndex((c) => c.slot === s);
    const c = at >= 0 ? left.splice(at, 1)[0] : null;
    const { x, y } = spots[j];
    return `<div class="slot ${c ? "filled" : ""} ${c && c.id === newest ? "new" : ""}" ${c ? `data-id="${esc(c.id)}"` : ""} style="left:${x}%;top:${y}%">
      <div class="disc">${c ? crest(c.crest, 48, c.club) + (c.rating == null ? "" : `<span class="r">${c.rating}</span>`) + `<span class="sl">${s}</span>` : s}</div>
      ${c ? `<div class="nm">${esc(c.name)}</div><div class="cl">${esc(c.short)} ${esc(c.season.slice(2))}</div>` : ""}
    </div>`;
  }).join("");
  slideFrom(el, was);
  if (FLIGHT) requestAnimationFrame(land);
  peekShow();
}

/* A pick lands. Take lifts the man off his row; when the reply has placed him, he flies
   to his place (the pitch, the bench, or the peek on a phone), and anyone the placement
   moved (C35 re-assigns after every pick) slides to his new slot. Display only: nothing
   here waits for it, and with reduced motion none of it runs. */
const CALM = matchMedia("(prefers-reduced-motion: reduce)");
let FLIGHT = null, SCROLL_DEST = null;

function takeoff(row, c) {
  if (!row || !c || FLIGHT || CALM.matches) return;
  const r = (row.querySelector(".pos") || row).getBoundingClientRect();
  const el = document.createElement("div");
  el.className = "flyer";
  el.setAttribute("aria-hidden", "true");
  el.innerHTML = `${crest(c.crest, 46, "")}<span class="fn">${esc(c.name)}</span>`;
  el.style.left = `${r.left + r.width / 2}px`;
  el.style.top = `${r.top + r.height / 2}px`;
  document.body.append(el);
  row.classList.add("taking");
  // A reply that never places him (refused, or lost) mustn't leave him hanging there.
  FLIGHT = { el, id: c.id, row, timer: setTimeout(dropFlight, 20000) };
}

/* The pick didn't happen: he goes back down. The pages call this when a pick fails. */
function dropFlight() {
  const f = FLIGHT;
  if (!f) return;
  FLIGHT = null;
  clearTimeout(f.timer);
  f.row.classList.remove("taking");
  f.el.animate([{ opacity: 1 }, { opacity: 0, transform: "scale(.6)" }], { duration: 220, fill: "forwards" }).onfinish = () => f.el.remove();
}

function land() {
  const f = FLIGHT;
  if (!f) return;
  const sel = `[data-id="${CSS.escape(f.id)}"]`;
  const peek = document.querySelector(".peek.on");
  const spot = (peek && peek.querySelector(sel)) || document.querySelector(`.pitch ${sel}, .bench-row ${sel}`);
  if (!spot) return;                                  // not placed yet: a later render lands him
  FLIGHT = null;
  clearTimeout(f.timer);
  // The flyer is fixed to the screen. A long squad scrolls the page back up to the next
  // deal as he leaves, so a place on the page is aimed at where it will be when the scroll
  // ends; the peek is fixed too, so it stays put.
  const onPeek = !!(peek && peek.contains(spot));
  const shift = onPeek || SCROLL_DEST == null ? 0 : scrollY - SCROLL_DEST;
  SCROLL_DEST = null;
  spot.classList.remove("new");                       // its pop would shrink what's measured
  spot.classList.add("awaiting");
  const aim = (spot.querySelector(".disc, .crest") || spot).getBoundingClientRect();
  const now = f.el.getBoundingClientRect();
  const x0 = now.left + now.width / 2, y0 = now.top + now.height / 2;
  const x1 = aim.left + aim.width / 2, y1 = aim.top + aim.height / 2 + shift;
  Object.assign(f.el.style, { left: `${x0}px`, top: `${y0}px`, animation: "none" });
  const dx = x1 - x0, dy = y1 - y0, arc = Math.min(90, 30 + Math.abs(dx) * 0.12);
  if (onPeek) peekHold(1500);
  f.el.querySelector(".fn").animate([{ opacity: 1 }, { opacity: 0 }], { duration: 260, fill: "forwards" });
  f.el.animate([
    { transform: "scale(1.08)" },
    { transform: `translate(${dx * 0.5}px,${dy * 0.5 - arc}px) scale(1.2)`, offset: 0.5 },
    { transform: `translate(${dx}px,${dy}px) scale(${aim.width / 46})` },
  ], { duration: 620 + Math.min(280, Math.abs(shift) * 0.25), easing: "cubic-bezier(.5,0,.25,1)", fill: "forwards" }).onfinish = () => {
    f.el.remove();
    spot.classList.remove("awaiting");
    spot.classList.add("new");                        // the pop and the ring, now he's there
  };
}

/* Where each placed man's centre is, inside `el`, before it is redrawn. */
function placesOf(el) {
  const at = new Map(), box = el.getBoundingClientRect();
  if (!box.width) return at;
  el.querySelectorAll("[data-id]").forEach((n) => {
    const r = n.getBoundingClientRect();
    at.set(n.dataset.id, [r.left + r.width / 2 - box.left, r.top + r.height / 2 - box.top]);
  });
  return at;
}

/* After a redraw, everyone who stood somewhere else slides from there. */
function slideFrom(el, was) {
  if (!was.size || CALM.matches) return;
  const box = el.getBoundingClientRect();
  el.querySelectorAll("[data-id]").forEach((n) => {
    const old = was.get(n.dataset.id);
    if (!old) return;
    const r = n.getBoundingClientRect();
    const dx = old[0] - (r.left + r.width / 2 - box.left), dy = old[1] - (r.top + r.height / 2 - box.top);
    if (Math.hypot(dx, dy) < 2) return;
    n.animate([{ translate: `${dx}px ${dy}px` }, { translate: "0px 0px" }], { duration: 520, easing: "cubic-bezier(.3,.7,.2,1)" });
  });
}

/* The peek: on a phone the pitch is below the deal, so you'd pick blind to your shape.
   While the deal's heading and the pitch are both out of sight, a small pitch on its side
   (attacking right) stays under the nav; a tap opens the real one over the page. `d` is a
   drafting side ({formation, xi, bench, bench_size}); null takes the peek away. */
let PEEK = null;
const ONE_COLUMN = matchMedia("(max-width: 980px)");

function pitchPeek(pitchEl, d) {
  if (!d) {
    if (PEEK) { PEEK.io.disconnect(); PEEK.el.remove(); PEEK = null; }
    return;
  }
  if (!PEEK) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "peek";
    document.body.append(el);
    const io = new IntersectionObserver((es) => { es.forEach((e) => PEEK.seen.set(e.target, e.isIntersecting)); peekShow(); });
    PEEK = { el, io, seen: new Map(), watched: [], hold: 0, d: null };
    el.onclick = peekOpen;
    ONE_COLUMN.addEventListener("change", peekShow);
  }
  // Rooms and the daily redraw the whole page, so what's watched may be new elements.
  const watch = [pitchEl, document.querySelector(".draft-top")].filter(Boolean);
  if (watch.length !== PEEK.watched.length || watch.some((w, k) => w !== PEEK.watched[k])) {
    PEEK.io.disconnect();
    PEEK.watched = watch;
    watch.forEach((w) => PEEK.io.observe(w));
  }
  // A room's turn bar is pinned under the nav too; the peek sits under it.
  const bar = document.querySelector(".turnbar");
  PEEK.el.style.top = bar && bar.offsetHeight ? `calc(var(--nav-h) + ${bar.offsetHeight + 6}px)` : "";
  const spots = slotSpots(d.formation.slots), left = [...d.xi];
  const dot = (c, style, label) => `<span class="pk ${c ? "filled" : ""}" ${c ? `data-id="${esc(c.id)}"` : ""} ${style}>${c ? crest(c.crest, 20, c.club) : label}</span>`;
  const was = placesOf(PEEK.el);
  PEEK.el.innerHTML = `<span class="pk-pitch"><i class="pk-box a"></i><i class="pk-box b"></i>${d.formation.slots.map((s, j) => {
    const at = left.findIndex((c) => c.slot === s);
    return dot(at >= 0 ? left.splice(at, 1)[0] : null, `style="left:${100 - spots[j].y}%;top:${spots[j].x}%"`, s);
  }).join("")}</span>` + (d.bench_size ? `<span class="pk-bench">${Array.from({ length: d.bench_size }, (_, k) => dot(d.bench[k], "", "")).join("")}</span>` : "");
  PEEK.el.setAttribute("aria-label", `Your XI so far: ${d.xi.length} of 11${d.bench_size ? `, bench ${d.bench.length} of ${d.bench_size}` : ""}. Show it.`);
  PEEK.d = d;
  slideFrom(PEEK.el, was);
  peekShow();
  if (FLIGHT) requestAnimationFrame(land);
}

function peekShow() {
  if (!PEEK) return;
  const { watched, seen } = PEEK;
  // Until the observer has reported on newly watched elements, leave it as it is.
  if (watched.some((w) => w.isConnected && !seen.has(w))) return;
  const live = watched.length && watched[0].isConnected;
  const on = live && ONE_COLUMN.matches && !document.querySelector(".peek-sheet")
    && (Date.now() < PEEK.hold || !watched.some((w) => seen.get(w)));
  PEEK.el.classList.toggle("on", !!on);
}

/* Keep the peek up a moment after a pick lands on it, whatever scrolls. */
function peekHold(ms) {
  PEEK.hold = Date.now() + ms;
  setTimeout(peekShow, ms + 20);
}

function peekOpen() {
  const d = PEEK.d, sheet = document.createElement("div");
  sheet.className = "peek-sheet";
  sheet.innerHTML = `<div class="peek-card" role="dialog" aria-modal="true" aria-label="Your XI">
    <div class="panel-h"><span class="label">Your XI · ${esc(d.formation.label)}</span><button class="btn small ghost" type="button">Back to the deal</button></div>
    <div class="pitch"></div><div class="bench-row" hidden></div></div>`;
  document.body.append(sheet);
  renderPitch(sheet.querySelector(".pitch"), d.formation.slots, d.xi, null);
  renderBench(sheet.querySelector(".bench-row"), d.bench, d.bench_size);
  peekShow();
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const close = () => { sheet.remove(); document.removeEventListener("keydown", onKey); peekShow(); PEEK && PEEK.el.focus(); };
  sheet.onclick = close;                              // a tap anywhere puts it away
  document.addEventListener("keydown", onKey);
  sheet.querySelector("button").focus();
}

/* Moving between pages. Where the browser has cross-document view transitions, the nav
   stays put and the page fades through (style.css), and a pitch marked `data-xi` on both
   pages carries its eleven across, each man to his place on the next. Names are given only
   for the transition, since a page may hold each name once. */
function nameEleven() {
  const p = document.querySelector("[data-xi]");
  if (!p) return;
  p.style.viewTransitionName = "xi-pitch";
  p.querySelectorAll(".slot[data-id]").forEach((s) => { s.style.viewTransitionName = `xi-${s.dataset.id.replace(/[^\w-]/g, "_")}`; });
}
// A transition the browser skips (a hidden tab, a slow page, a page that doesn't opt in)
// rejects its promises; that is not a failure of the page, and unhandled it would be
// reported as one. Where the event hands us the transition, all three are caught here. A
// hidden page's incoming transition is skipped before `pagereveal` fires, so no script ever
// holds its promises: the rejection handler above drops it by its error instead.
const onTransition = (e) => {
  const vt = e.viewTransition;
  if (!vt) return;
  for (const p of [vt.ready, vt.finished, vt.updateCallbackDone]) p && p.catch(() => {});
  nameEleven();
};
function skippedTransition(err) {
  return err instanceof DOMException && /transition/i.test(err.message);
}
addEventListener("pageswap", onTransition);
addEventListener("pagereveal", onTransition);

/* The next page's first request, made on this one and handed over in this tab's
   sessionStorage, so it can draw at once (which is what the transition shows). Taken
   once; a page that finds nothing asks as it always did. */
const handoff = {
  put(key, value) { try { sessionStorage.setItem(`h:${key}`, JSON.stringify(value)); } catch {} },
  take(key) {
    try {
      const v = sessionStorage.getItem(`h:${key}`);
      sessionStorage.removeItem(`h:${key}`);
      return v ? JSON.parse(v) : null;
    } catch { return null; }
  },
};

/* To a finished draft's squad page, its figures fetched first; `wait` lets a pick land. */
async function goSquad(state, wait = 0) {
  const pause = new Promise((r) => setTimeout(r, wait));
  try { handoff.put(`squad:${state}`, await api(`/api/draft/${state}/squad`)); } catch {}
  await pause;
  location.href = `/squad#${state}`;
}

/* The team sheet (C44): once a bench draft is finished, tap a man and then where he should
   go: another slot (he stands there and the rest make room), a substitute (they change
   places) or, for a substitute, a starter he replaces. The server says where each man can
   go (`to` on every card: "s<slot>" or "b<bench place>") and does the moving, everyone else
   shifting as little as possible. `d` is a finished draft ({xi in slot order, bench});
   `opts.onMove(man, to)` sends one move, `opts.reset` (if the sheet was chosen) puts back
   the drafted order, `opts.hint` is a line to talk in. */
function sheetEditor(pitchEl, benchEl, d, opts) {
  const men = [...d.xi.map((c, j) => ({ c, at: `s${j}`, where: c.slot })), ...d.bench.map((c, k) => ({ c, at: `b${k}`, where: `sub ${k + 1}` }))];
  const els = [...pitchEl.querySelectorAll(".slot"), ...benchEl.querySelectorAll(".sub-card")];
  if (els.length !== men.length) return;
  const say = (t) => { if (opts.hint) opts.hint.innerHTML = t; };
  const idle = () => {
    say(`Tap a player, then where he should go: another position, or a substitute to change places with.
      Everyone else moves as little as possible to make room.
      ${opts.reset ? `<button class="linkish" id="sheetreset">Back to the drafted line-up</button>` : ""}`);
    if ($("sheetreset")) $("sheetreset").onclick = opts.reset;
  };
  let sel = null;
  const paint = () => {
    [pitchEl, benchEl].forEach((e) => e.classList.toggle("choosing", sel !== null));
    els.forEach((el, n) => {
      el.classList.toggle("sel", sel === n);
      el.classList.toggle("can", sel !== null && (men[sel].c.to || []).includes(men[n].at));
    });
  };
  els.forEach((el, n) => {
    const m = men[n];
    el.classList.add("pickable");
    el.tabIndex = 0;
    el.setAttribute("role", "button");
    el.setAttribute("aria-label", `${m.c.name}, ${m.where}`);
    const go = () => {
      if (sel === null) {
        sel = n; paint();
        const ps = (m.c.positions || [m.c.pos]).join(" · ");
        say((m.c.to || []).length
          ? `<b>${esc(m.c.name)}</b> plays ${esc(ps)}. Tap a highlighted place, or him again to cancel.`
          : `<b>${esc(m.c.name)}</b> plays ${esc(ps)}, and nowhere else is free for him in this shape. Tap him again to cancel.`);
        return;
      }
      if (sel === n) { sel = null; paint(); idle(); return; }
      const from = men[sel];
      if (!(from.c.to || []).includes(m.at)) { toast(`${from.c.name} can't go there`); return; }
      sel = null; paint();
      opts.onMove(from.c.p, m.at);
    };
    el.onclick = go;
    el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } };
  });
  idle();
}

/* A plan made for one sheet, for another, as the server's carry_plan does: each line follows
   its substitute (dropped if he now starts) and its named starter (back to "best change"
   if he no longer starts or that substitute can't replace him). For a plan not yet sent. */
function carryPlan(plan, before, after) {
  if (!plan) return plan;
  const benchIds = after.bench.map((c) => c.id), xiIds = after.xi.map((c) => c.id);
  return plan.flatMap((x) => {
    const on = benchIds.indexOf(before.bench[x.on].id);
    if (on < 0) return [];
    let off = x.off == null ? null : xiIds.indexOf(before.xi[x.off].id);
    if (off != null && (off < 0 || !after.bench[on].can_replace.includes(off))) off = null;
    return [{ ...x, on, off }];
  });
}

/* A formation drawn on a pitch (C37): eleven discs, created once and then moved, so a change
   of shape slides each into its new place. `el` is a .pitch; `f` a formation from /api/meta. */
function shapePitch(el, f) {
  if (el.children.length !== 11) el.innerHTML = Array.from({ length: 11 }, () => `<div class="slot pv-slot"><div class="disc"></div></div>`).join("");
  const spots = slotSpots(f.slots);
  [...el.children].forEach((d, j) => {
    d.style.left = `${spots[j].x}%`;
    d.style.top = `${spots[j].y}%`;
    d.dataset.line = LINE_OF[f.slots[j]];
    d.firstElementChild.textContent = f.slots[j];
  });
  el.setAttribute("aria-label", `${f.label}: ${f.slots.join(", ")}`);
}

/* The compact version for a lobby: a small pitch with the shape's name and line beside it. */
function shapeBox(id) {
  return `<div class="shape-pv"><div class="pitch" id="${id}-pitch" role="img"></div>
    <div class="shape-txt"><b id="${id}-name"></b><p id="${id}-about"></p></div></div>`;
}
function showShape(id, f) {
  if (!$(`${id}-pitch`) || !f) return;
  shapePitch($(`${id}-pitch`), f);
  $(`${id}-name`).textContent = f.label;
  $(`${id}-about`).textContent = f.about;
}

/* Hovering a formation chip previews it; leaving the chips shows the chosen one again. */
function previewOnHover(chipsEl, byCode, attr, show, current) {
  chipsEl.onmouseover = (e) => { const b = e.target.closest(`[${attr}]`); if (b) show(byCode[b.getAttribute(attr)]); };
  chipsEl.onmouseleave = () => show(byCode[current()]);
}

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode: not remembered */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* nothing kept to remove */ } },
};

// A solo draft is known by its seed (with the bench's "b"): its sheet and plan change the
// rest of the link after the picks, and it stays the same draft.
const draftedKey = (state) => `drafted:${state.split("-")[0]}`;
