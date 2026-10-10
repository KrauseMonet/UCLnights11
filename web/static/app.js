"use strict";

// The whole draft lives in the URL (#d=STATE); the server replays it on every
// request and keeps nothing. Reloading or sharing the link reproduces it exactly.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const POS_NAME = { GK: "Goalkeepers", DF: "Defenders", MF: "Midfielders", FW: "Forwards" };
const LAYOUT = {           // rows from the back, as counts per row
  433: { GK: [1], DF: [4], MF: [3], FW: [3] },
  442: { GK: [1], DF: [4], MF: [4], FW: [2] },
  4231: { GK: [1], DF: [4], MF: [2, 3], FW: [1] },
  352: { GK: [1], DF: [3], MF: [5], FW: [2] },
  343: { GK: [1], DF: [3], MF: [4], FW: [3] },
};

let META = null;
let FORMATION = "433";
let SESSION = null;
let CUP = null;
let busy = false;

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

function show(id) {
  for (const s of document.querySelectorAll(".screen")) s.hidden = s.id !== id;
  window.scrollTo({ top: 0 });
}

function ratingClass(r) {
  return r >= 90 ? "r90" : r >= 85 ? "r85" : r >= 80 ? "r80" : "";
}

// ---------------------------------------------------------------- home

function renderHome() {
  const box = $("formations");
  box.innerHTML = META.formations.map((f) =>
    `<button role="radio" aria-checked="${f.code === FORMATION}" data-f="${f.code}">${esc(f.label)}</button>`).join("");
  box.onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    FORMATION = b.dataset.f;
    renderHome();
  };
  show("home");
}

$("start").onclick = async () => {
  if (busy) return;
  busy = true;
  try {
    const s = await api("/api/draft", { method: "POST", body: JSON.stringify({ formation: FORMATION }) });
    setDraft(s);
  } catch (e) { toast(e.message); } finally { busy = false; }
};

// ---------------------------------------------------------------- draft

function setDraft(s, fresh = true) {
  SESSION = s;
  history.replaceState(null, "", `#d=${s.state}`);
  if (s.complete) return loadCup(s.state);
  renderDraft(fresh);
}

function renderDraft(fresh) {
  const s = SESSION;
  show("draft");
  $("pickno").textContent = Math.min(s.picks.length + 1, 11);
  $("formname").textContent = s.formation.label;
  $("rerolls").textContent = `(${s.rerolls_left})`;
  $("reroll").disabled = s.rerolls_left <= 0;
  renderDeal(s.deal, fresh);
  renderPitch($("pitch"), s.formation.code, s.picks, s.picks.length ? s.picks[s.picks.length - 1].id : null);
}

function renderDeal(d, fresh) {
  const el = $("deal");
  const byPos = { GK: [], DF: [], MF: [], FW: [] };
  d.cards.forEach((c, i) => byPos[c.pos].push([c, i]));
  const lines = Object.entries(byPos).filter(([, cs]) => cs.length).map(([pos, cs]) =>
    `<div class="linehead">${POS_NAME[pos]}</div>` + cs.map(([c, i]) => `
      <button class="card" data-i="${i}" ${c.takeable ? "" : "disabled"} title="${esc(c.takeable ? "Take " + c.name : c.reason)}">
        <span class="rating ${ratingClass(c.rating)}">${c.rating}</span>
        <span class="who"><b>${esc(c.name)}</b><small><span class="pos ${c.pos}">${c.pos}</span> ${esc(c.nation || "")}</small></span>
        ${c.takeable ? "" : `<span class="why">${esc(c.reason)}</span>`}
      </button>`).join("")).join("");
  el.innerHTML = `
    <div class="dealhead" style="background:linear-gradient(90deg, rgba(0,0,0,.55), rgba(0,0,0,.05) 70%), linear-gradient(120deg, ${d.primary}, ${d.secondary === "#FFFFFF" ? d.primary : d.secondary})">
      <div class="season">${esc(d.season)}</div><h2>${esc(d.name)}</h2>
    </div>
    <div class="cards">${lines}</div>`;
  if (fresh) { el.classList.remove("flip"); void el.offsetWidth; el.classList.add("flip"); }
  el.querySelectorAll(".card:not(:disabled)").forEach((b) => b.onclick = () => pick(+b.dataset.i));
}

function renderPitch(el, code, picks, newest) {
  const layout = LAYOUT[code];
  const ys = { GK: [91], DF: [72], MF: layout.MF.length === 2 ? [55, 38] : [48], FW: [17] };
  const html = [];
  for (const pos of ["GK", "DF", "MF", "FW"]) {
    const taken = picks.filter((c) => c.pos === pos);
    let k = 0;
    layout[pos].forEach((n, row) => {
      for (let j = 0; j < n; j++, k++) {
        const c = taken[k];
        const x = ((j + 1) / (n + 1)) * 100;
        const y = ys[pos][row];
        html.push(`<div class="slot ${c ? "filled" : ""} ${c && c.id === newest ? "new" : ""}" style="left:${x}%;top:${y}%">
          <div class="disc">${c ? c.rating : pos}</div>
          ${c ? `<div class="nm">${esc(c.name)}</div><div class="cl">${esc(c.short)} ${esc(c.season.slice(2))}</div>` : ""}
        </div>`);
      }
    });
  }
  el.innerHTML = html.join("");
}

async function pick(i) {
  if (busy) return;
  busy = true;
  try {
    setDraft(await api(`/api/draft/${SESSION.state}/pick`, { method: "POST", body: JSON.stringify({ index: i }) }));
  } catch (e) { toast(e.message); } finally { busy = false; }
}

$("reroll").onclick = async () => {
  if (busy || !SESSION || SESSION.rerolls_left <= 0) return;
  busy = true;
  try { setDraft(await api(`/api/draft/${SESSION.state}/reroll`, { method: "POST" })); }
  catch (e) { toast(e.message); } finally { busy = false; }
};

// ---------------------------------------------------------------- tournament

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode: progress just isn't remembered */ } },
};

async function loadCup(state) {
  show("cup");
  $("cuphead").innerHTML = `<h2>Drawing the groups…</h2>`;
  $("cupbody").innerHTML = "";
  $("cupnav").innerHTML = "";
  try {
    CUP = await api(`/api/tournament/${state}`);
  } catch (e) { $("cuphead").innerHTML = `<h2>Something went wrong</h2><p>${esc(e.message)}</p>`; return; }
  CUP.state = state;
  CUP.revealed = Math.min(+(store.get(`cup:${state}`) || 0), CUP.your_matches.length);
  renderCup();
}

function sideName(side) {
  return side.you ? `<span class="youname">Your XI</span>` : esc(side.name);
}

function scoreLine(f) {
  let s = `${f.hg}–${f.ag}`;
  return s;
}

function fixtureMeta(f) {
  const bits = [`${f.stage === "Group stage" ? "Group " + f.group + " · " : ""}${f.label}`];
  if (f.extra_time) bits.push("after extra time");
  if (f.pens) bits.push(`${f.pens[0]}–${f.pens[1]} on penalties`);
  return bits.join(" · ");
}

function outcome(f) {
  const you = f.home.you ? 0 : 1;
  const mine = you === 0 ? f.hg : f.ag, theirs = you === 0 ? f.ag : f.hg;
  if (f.pens) return (you === 0 ? f.pens[0] > f.pens[1] : f.pens[1] > f.pens[0]) ? "w" : "l";
  return mine > theirs ? "w" : mine < theirs ? "l" : "d";
}

function fixtureHtml(f) {
  return `<div class="fixture ${f.home.you || f.away.you ? outcome(f) : ""}">
    <div class="h">${sideName(f.home)}</div><div class="sc">${scoreLine(f)}</div><div>${sideName(f.away)}</div>
    <div class="meta">${esc(fixtureMeta(f))}</div></div>`;
}

function renderCup() {
  const done = CUP.revealed >= CUP.your_matches.length;
  const nav = $("cupnav");
  if (!done) {
    const next = CUP.your_matches[CUP.revealed];
    $("cuphead").innerHTML = `<h2>Your campaign</h2><p>${esc(next.stage === "Group stage" ? "Group " + next.group : next.stage)} · ${esc(next.label)}</p>`;
    nav.innerHTML = `<button class="go" id="next">Play next match</button><button class="ghost" id="skip">Skip to the end</button>`;
    $("next").onclick = playNext;
    $("skip").onclick = () => { CUP.revealed = CUP.your_matches.length; store.set(`cup:${CUP.state}`, CUP.revealed); $("match").hidden = true; renderCup(); };
  } else {
    const champ = CUP.reached === "Champions";
    $("cuphead").innerHTML = champ
      ? `<h2 class="champ">Campeones</h2><p>Your XI won the whole thing.</p>`
      : `<h2>${esc(CUP.reached)}</h2><p>${esc(CUP.champion.name)} lifted the trophy.</p>`;
    nav.innerHTML = `<button class="go" id="again">Draft again</button><button class="ghost" id="copy">Copy link</button>`;
    $("again").onclick = () => { history.replaceState(null, "", "/"); renderHome(); };
    $("copy").onclick = () => navigator.clipboard.writeText(location.href).then(() => toast("Link copied"), () => toast(location.href));
  }
  renderCupBody(done);
}

function renderCupBody(done) {
  const played = CUP.your_matches.slice(0, CUP.revealed);
  const parts = [];
  if (played.length) parts.push(`<div class="panel"><h3>Your results</h3>${played.map(fixtureHtml).join("")}</div>`);
  parts.push(`<div class="panel"><h3>Your XI · ${esc(CUP.you.formation)}</h3><div class="pitch" id="cuppitch" style="max-width:420px;margin:0 auto"></div></div>`);
  if (done) {
    parts.push(`<div class="panel"><h3>Groups</h3><div class="groups">${CUP.groups.map(groupHtml).join("")}</div></div>`);
    parts.push(`<div class="panel"><h3>Knockouts</h3><div class="rounds">${CUP.knockout.map(roundHtml).join("")}</div></div>`);
    parts.push(`<div class="panel"><h3>Top scorers</h3><ol class="boot">${CUP.golden_boot.map((r) =>
      `<li><span>${r.you ? `<span class="youname">${esc(r.name)}</span>` : esc(r.name)} <small style="color:var(--muted)">${esc(r.side)}</small></span><b>${r.goals}</b></li>`).join("")}</ol></div>`);
  }
  $("cupbody").innerHTML = parts.join("");
  renderPitch($("cuppitch"), CUP.you.xi.length ? formationCode(CUP.you.formation) : "433", CUP.you.xi, null);
}

function formationCode(label) {
  return label.replaceAll("-", "");
}

function groupHtml(g) {
  return `<div><table><thead><tr><th>Group ${g.name}</th><th>P</th><th>GD</th><th>Pts</th></tr></thead><tbody>${
    g.table.map((r, i) => `<tr class="${r.you ? "you" : ""} ${i < 2 ? "through" : ""}">
      <td><span class="badge" style="background:${r.primary}"></span>${r.you ? "Your XI" : esc(r.name)}</td>
      <td>${r.p}</td><td>${r.gf - r.ga > 0 ? "+" : ""}${r.gf - r.ga}</td><td><b>${r.pts}</b></td></tr>`).join("")
  }</tbody></table></div>`;
}

function roundHtml(r) {
  return `<div><div class="linehead">${esc(r.stage)}</div>${r.ties.map((t) => {
    const aw = t.winner === t.a.key, single = t.legs.length === 1;
    const score = (side, n) => single ? (side === "a" ? t.legs[0].hg : t.legs[0].ag) : n;
    const pens = t.legs[t.legs.length - 1].pens;
    return `<div class="tie">
      <div class="${aw ? "win" : "lose"}"><span>${t.a.you ? "Your XI" : esc(t.a.name)}</span><span>${score("a", t.agg[0])}</span></div>
      <div class="${aw ? "lose" : "win"}"><span>${t.b.you ? "Your XI" : esc(t.b.name)}</span><span>${score("b", t.agg[1])}</span></div>
      ${pens ? `<small style="color:var(--muted)">penalties ${pens[0]}–${pens[1]}</small>` : ""}
    </div>`;
  }).join("")}</div>`;
}

// A match plays out on a ticking clock with each goal landing at its minute.
function playNext() {
  const f = CUP.your_matches[CUP.revealed];
  const box = $("match");
  box.hidden = false;
  $("cupnav").innerHTML = `<button class="ghost" id="fast">Skip match</button>`;
  const end = f.extra_time ? 120 : 90;
  box.innerHTML = `
    <div class="stage">${esc(f.stage === "Group stage" ? "Group " + f.group + " · " + f.label : f.stage + " · " + f.label)}</div>
    <div class="scoreboard"><div class="t h">${sideName(f.home)}</div><div class="score" id="sc">0–0</div><div class="t">${sideName(f.away)}</div></div>
    <div class="clock" id="clk">0'</div><div class="timeline"><i id="bar"></i></div>
    <ul class="events" id="ev"></ul>`;
  box.scrollIntoView({ behavior: "smooth", block: "start" });
  let minute = 0, h = 0, a = 0, gi = 0;
  const finish = () => {
    clearInterval(timer);
    $("sc").textContent = `${f.hg}–${f.ag}`;
    $("clk").textContent = f.pens ? `Penalties: ${f.pens[0]}–${f.pens[1]}` : f.extra_time ? "After extra time" : "Full time";
    $("bar").style.width = "100%";
    while (gi < f.goals.length) addGoal(f.goals[gi++]);
    CUP.revealed += 1;
    store.set(`cup:${CUP.state}`, CUP.revealed);
    setTimeout(renderCup, 600);
  };
  const addGoal = (g) => {
    const li = document.createElement("li");
    li.className = g.side === 0 ? "h" : "a";
    li.textContent = `⚽ ${g.minute}' ${g.scorer}${g.assist ? ` (${g.assist})` : ""}`;
    $("ev").appendChild(li);
  };
  const timer = setInterval(() => {
    minute += 1;
    $("clk").textContent = `${minute}'`;
    $("bar").style.width = `${(minute / end) * 100}%`;
    while (gi < f.goals.length && f.goals[gi].minute <= minute) {
      const g = f.goals[gi++];
      g.side === 0 ? h++ : a++;
      $("sc").textContent = `${h}–${a}`;
      $("sc").classList.remove("goalflash"); void $("sc").offsetWidth; $("sc").classList.add("goalflash");
      addGoal(g);
    }
    if (minute >= end) finish();
  }, 55);
  $("fast").onclick = finish;
}

// ---------------------------------------------------------------- boot

(async function boot() {
  try {
    META = await api("/api/meta");
    FORMATION = META.default_formation;
    $("deckstat").textContent = `${META.club_seasons} squads · ${META.cards.toLocaleString()} players · ${META.first_season} to ${META.last_season}`;
  } catch (e) { toast("Could not reach the server"); return; }
  const m = location.hash.match(/^#d=([\w.-]+)$/);
  if (m) {
    try { return setDraft(await api(`/api/draft/${m[1]}`), true); }
    catch (e) { toast(e.message); history.replaceState(null, "", "/"); }
  }
  renderHome();
})();
