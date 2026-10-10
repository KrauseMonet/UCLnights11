"use strict";
/* Shared by every page: the nav and footer, the API helper, and the small renderers
   (crest medallion, rating chip, team colours, the pitch) that make the pages one site. */

const SITE_NAME = "UCLnights11";
// The wordmark: "nights" in gold, the casing exactly as the name is written.
const SITE_MARK = "UCL<b>nights</b>11";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const BRAND_SVG = `<svg viewBox="0 0 30 32" aria-hidden="true"><defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="#ffd873"/><stop offset="1" stop-color="#f5b83d"/></linearGradient></defs>
  <path d="M15 1 28 6v10c0 8-6 13-13 15C8 29 2 24 2 16V6z" fill="none" stroke="url(#bg)" stroke-width="2.2"/>
  <path d="m15 8 2.2 4.6 5 .7-3.6 3.5.9 5-4.5-2.4-4.5 2.4.9-5L7.8 13.3l5-.7z" fill="url(#bg)"/></svg>`;

function shell(active) {
  const nav = document.createElement("header");
  nav.className = "topnav";
  nav.innerHTML = `<div class="topnav-in">
    <a class="brand" href="/">${BRAND_SVG}<span>${SITE_MARK}</span></a>
    <nav class="navlinks">
      <a href="/draft" ${active === "draft" ? 'class="on"' : ""}>Draft</a>
      <a href="/archive" ${active === "archive" ? 'class="on"' : ""}>Archive</a>
    </nav>
    <div class="nav-r"><span class="nav-stat" id="navstat"></span></div></div>`;
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
}

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
  return body;
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

function rate(r) {
  const cls = r >= 90 ? "r90" : r >= 85 ? "r85" : r >= 80 ? "r80" : "";
  return `<span class="rate ${cls}">${r}</span>`;
}

/* Team colours as inline custom properties: the stylesheet does the rest. */
function teamStyle(x) {
  return `--team:${x.team};--team-deep:${x.deep};--team-ink:${x.ink}`;
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
