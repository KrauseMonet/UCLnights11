"use strict";
/* Shared by every page: the nav and footer, the API helper, the account control and its
   sign-in dialog, and the small renderers (crest medallion, rating chip, team colours,
   the dealt squad, the pitch) that make the pages one site. */

const SITE_NAME = "UCLnights11";
// The logo the user supplied, cut out by tools.build_brand.
const SITE_LOGO = "/static/brand/logo.webp";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function shell(active) {
  const nav = document.createElement("header");
  nav.className = "topnav";
  nav.innerHTML = `<div class="topnav-in">
    <a class="brand" href="/" aria-label="${esc(SITE_NAME)} home"><img src="${SITE_LOGO}" alt="${esc(SITE_NAME)}" width="129" height="32"></a>
    <nav class="navlinks">
      <a href="/draft" ${active === "draft" ? 'class="on"' : ""}>Draft</a>
      <a href="/friends" ${active === "friends" ? 'class="on"' : ""}>Friends</a>
      <a href="/archive" ${active === "archive" ? 'class="on"' : ""}>Archive</a>
    </nav>
    <div class="nav-r"><span class="nav-stat" id="navstat"></span><span class="nav-acct" id="navacct"></span></div></div>`;
  document.body.prepend(nav);
  const foot = document.createElement("footer");
  foot.className = "foot";
  foot.innerHTML = `<p>Squads from Wikipedia (CC BY-SA). Club crests belong to their clubs and appear here on a
    non-commercial fan site. Ratings are this game's own judgement. Real results for the match engine come from
    openfootball (CC0).</p><p>An independent fan game, not affiliated with UEFA or any club.</p>`;
  document.body.append(foot);
  const t = document.createElement("div");
  t.className = "toast"; t.id = "toast"; t.setAttribute("role", "status");
  document.body.append(t);
  loadMe();
}

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
  return body;
}

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
    el.innerHTML = ME
      ? `<span class="who-me" title="Signed in">${esc(ME.username)}</span><button class="linkish" id="signout">Sign out</button>`
      : `<button class="btn small ghost" id="signin">Sign in</button>`;
    const out = $("signout"), inn = $("signin");
    if (out) out.onclick = async () => { await api("/api/auth/logout", { method: "POST" }).catch(() => {}); setMe(null); };
    if (inn) inn.onclick = () => openAuth();
  }
  authListeners.forEach((f) => f(ME));
}

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

function renderDeal(el, d, opts) {
  const byLine = { GK: [], DF: [], MF: [], FW: [] };
  d.cards.forEach((c, i) => byLine[c.pos].push([c, i]));
  const open = d.cards.filter((c) => c.takeable).length;
  const rows = Object.entries(byLine).filter(([, cs]) => cs.length).map(([pos, cs]) =>
    `<div class="line-h">${LINES[pos]}</div>` + cs.map(([c, i]) => `
      <div class="row ${c.takeable ? "" : "off"}">
        <span class="pos ${c.pos}">${c.pos}</span>
        <div class="who"><b>${esc(c.name)}</b><small>${esc(c.nation || "")}</small></div>
        ${rate(c.rating)}
        ${c.takeable ? `<button class="take" data-i="${i}" aria-label="Take ${esc(c.name)}">Take</button>`
                     : `<span class="why">${esc(c.reason)}</span>`}
      </div>`).join("")).join("");
  el.style.cssText = teamStyle(d);
  el.innerHTML = `
    <div class="panel-h"><span class="label">${esc(opts.heading || "Dealt to you")}</span><span class="label"><b>${open}</b> of ${d.cards.length} available</span></div>
    <div class="band">
      ${crest(d.crest, 104, d.name)}
      <div class="deal-year">${esc(d.season)}</div>
      <div class="deal-club">${esc(d.name)}</div>
      <div class="deal-actions">
        <button class="btn small" data-reroll ${opts.rerollsLeft ? "" : "disabled"}>Another squad</button>
        <span class="label" style="color:rgba(255,255,255,.65)">${opts.rerollsLeft} left</span>
      </div>
    </div>
    <div>${rows}</div>`;
  if (opts.fresh) { el.classList.remove("flip"); void el.offsetWidth; el.classList.add("flip"); }
  el.querySelectorAll(".take").forEach((b) => b.onclick = () => opts.onTake(+b.dataset.i));
  el.querySelector("[data-reroll]").onclick = opts.onReroll;
}

const LAYOUT = {           // rows from the back, counts per row
  433: { GK: [1], DF: [4], MF: [3], FW: [3] },
  442: { GK: [1], DF: [4], MF: [4], FW: [2] },
  4231: { GK: [1], DF: [4], MF: [2, 3], FW: [1] },
  352: { GK: [1], DF: [3], MF: [5], FW: [2] },
  343: { GK: [1], DF: [3], MF: [4], FW: [3] },
};

function renderPitch(el, code, picks, newest) {
  const layout = LAYOUT[code];
  const ys = { GK: [90], DF: [70], MF: layout.MF.length === 2 ? [53, 36] : [46], FW: [16] };
  const html = [];
  for (const pos of ["GK", "DF", "MF", "FW"]) {
    const taken = picks.filter((c) => c.pos === pos);
    let k = 0;
    layout[pos].forEach((n, row) => {
      for (let j = 0; j < n; j++, k++) {
        const c = taken[k];
        const x = ((j + 1) / (n + 1)) * 100, y = ys[pos][row];
        html.push(`<div class="slot ${c ? "filled" : ""} ${c && c.id === newest ? "new" : ""}" style="left:${x}%;top:${y}%">
          <div class="disc">${c ? crest(c.crest, 48, c.club) + `<span class="r">${c.rating}</span>` : pos}</div>
          ${c ? `<div class="nm">${esc(c.name)}</div><div class="cl">${esc(c.short)} ${esc(c.season.slice(2))}</div>` : ""}
        </div>`);
      }
    });
  }
  el.innerHTML = html.join("");
}

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode: not remembered */ } },
};
