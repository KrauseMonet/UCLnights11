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
      <a href="/draft" ${active === "draft" ? 'class="on"' : ""}>Draft</a>
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
  loadMe();
  installable();
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
   because it may have landed even though the reply was lost. */
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
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), API_TIMEOUT_MS);
  let res;
  try {
    res = await fetch(path, { headers: { "Content-Type": "application/json" }, signal: ctl.signal, ...opts });
  } catch (e) {
    throw new ApiError(navigator.onLine === false ? "You're offline" : "Couldn't reach the server", 0);
  } finally { clearTimeout(timer); }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new ApiError(body.detail || `Request failed (${res.status})`, res.status, body);
    if (res.status >= 500) reportFailure("api", `${opts.method || "GET"} ${path.split("?")[0]} ${res.status}`);
    throw err;
  }
  return body;
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
        ${opts.readOnly ? (c.takeable ? "" : `<span class="why">${esc(c.reason)}</span>`)
          : c.takeable ? `<button class="take" data-i="${i}" aria-label="Take ${esc(c.name)}">Take</button>`
                     : `<span class="why">${esc(c.reason)}</span>`}
      </div>`).join("")).join("");
  el.style.cssText = teamStyle(d);
  el.innerHTML = `
    <div class="panel-h"><span class="label">${opts.headingHtml || esc(opts.heading || "Dealt to you")}</span><span class="label"><b>${open}</b> of ${d.cards.length} available</span></div>
    <div class="band">
      ${crest(d.crest, 104, d.name)}
      <div class="deal-year">${esc(d.season)}</div>
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
    if (el.getBoundingClientRect().top < 0) (document.querySelector(".draft-top") || el).scrollIntoView({ block: "start", behavior: "smooth" });
  }
  el.querySelectorAll(".take").forEach((b) => b.onclick = () => opts.onTake(+b.dataset.i));
  if (opts.onReroll) el.querySelector("[data-reroll]").onclick = opts.onReroll;
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

/* Where each position stands on the pitch, attacking upwards: [top %, left %] for one man;
   a position held more than once spreads across the middle by GAP. */
const SPOT = { GK: [90, 50], RB: [67, 86], CB: [70, 50], LB: [67, 14], DM: [55, 50], CM: [44, 50],
  AM: [30, 50], RM: [41, 87], LM: [41, 13], RW: [20, 82], ST: [11, 50], LW: [20, 18] };
const GAP = { CB: 25, CM: 32, DM: 24, ST: 24, AM: 30 };

function slotSpots(slots) {
  const count = {}, seen = {};
  slots.forEach((s) => { count[s] = (count[s] || 0) + 1; });
  const pivot = count.DM === 1 && count.CM === 1;   // a double pivot sits side by side
  return slots.map((s) => {
    const k = (seen[s] = (seen[s] || 0) + 1), n = count[s];
    let [y, x] = SPOT[s];
    if (n > 1) x = 50 + (k - (n + 1) / 2) * (GAP[s] || 24);
    if (pivot && s === "DM") { x = 38; y = 53; }
    if (pivot && s === "CM") { x = 62; y = 49; }
    return { x, y };
  });
}

function renderPitch(el, slots, xi, newest) {
  const spots = slotSpots(slots);
  const left = [...xi];
  el.innerHTML = slots.map((s, j) => {
    const at = left.findIndex((c) => c.slot === s);
    const c = at >= 0 ? left.splice(at, 1)[0] : null;
    const { x, y } = spots[j];
    return `<div class="slot ${c ? "filled" : ""} ${c && c.id === newest ? "new" : ""}" style="left:${x}%;top:${y}%">
      <div class="disc">${c ? crest(c.crest, 48, c.club) + (c.rating == null ? "" : `<span class="r">${c.rating}</span>`) + `<span class="sl">${s}</span>` : s}</div>
      ${c ? `<div class="nm">${esc(c.name)}</div><div class="cl">${esc(c.short)} ${esc(c.season.slice(2))}</div>` : ""}
    </div>`;
  }).join("");
}

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode: not remembered */ } },
};
