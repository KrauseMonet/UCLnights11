"use strict";
/* The profile (C31): one account's saved tournaments and daily challenges, added up.
   Everything here was worked out by the server replaying each result when it was saved. */

shell("profile");
const PF_GOLD = "#c08a1e";   // the analysis's validated gold for a single series (C28)

const sourceLabel = { solo: "Solo", room: "Room", daily: "Daily" };
const resultHref = (r) => r.source === "solo" ? `/cup#${r.key}` : r.source === "room" ? `/cup?room=${r.key}` : `/daily#${r.key}`;
const when = (iso) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

function tiles(p) {
  const t = [
    [p.tournaments, "Tournaments"], [p.titles, "Titles"], [p.finals, "Finals"], [p.best_finish || "–", "Best finish"],
    [p.matches ? `${Math.round((p.won / p.matches) * 100)}%` : "–", "Matches won"],
    [p.daily.played, `Dailies · ${p.daily.met} met`], [p.daily.streak, `Daily streak · best ${p.daily.best_streak}`],
  ];
  return `<div class="an-tiles pf-tiles">${t.map(([v, l]) => `<div class="an-tile"><b class="${/^[\d%–]+$/.test(String(v)) ? "" : "txt"}">${esc(String(v))}</b><span>${esc(l)}</span></div>`).join("")}</div>`;
}

/* How far you get: one bar per finish, single series, numbers on the bars. */
function finishesHtml(p) {
  const top = Math.max(1, ...p.finishes.map((f) => f.n));
  return `<section class="panel an-panel"><div class="panel-h pf-ph"><span class="label">How far you get</span><span class="label">${p.tournaments} tournament${p.tournaments === 1 ? "" : "s"}</span></div>
    <div class="pf-finishes">${p.finishes.map((f) => `<div class="pf-fin" title="${esc(f.stage)}: ${f.n}">
      <span class="pf-fin-l">${esc(f.stage)}</span><div class="an-hbar"><i style="width:${(f.n / top) * 100}%;background:${PF_GOLD}"></i><b>${f.n}</b></div></div>`).join("")}</div></section>`;
}

function boardHtml(title, rows, fmt, note = "") {
  const lead = rows.length ? rows[0].value : 1;
  return `<div class="panel an-board"><div class="panel-h"><span class="label">${title}</span>${note ? `<small class="an-note">${note}</small>` : ""}</div>
    ${rows.length ? `<ol>${rows.map((r) => `<li>${crest(r.crest, 22, r.name)}<div class="who"><b>${esc(r.name)}</b>
      <small>${r.pos} · ${r.apps} app${r.apps === 1 ? "" : "s"}</small><div class="an-lead"><i style="width:${(r.value / lead) * 100}%"></i></div></div>
      <span class="n">${fmt(r.value)}</span></li>`).join("")}</ol>` : `<p class="empty">Nothing yet.</p>`}</div>`;
}

function recentHtml(p) {
  if (!p.recent.length) return `<section class="panel gate"><div><h2>Nothing saved yet</h2>
    <p>Finish a tournament you drafted here, or a friends' room, and it saves itself; a link someone sent you saves with <b>Save to profile</b>. Today's daily challenge saves itself too.</p></div>
    <div class="gate-cta"><a class="btn primary" href="/daily">Today's challenge</a><a class="btn ghost" href="/draft">Start a draft</a></div></section>`;
  return `<section class="panel"><div class="panel-h"><span class="label">Recent</span><span class="label">tap to see it again</span></div>
    ${p.recent.map((r) => `<a class="myroom pf-row" href="${esc(resultHref(r))}">
      <span class="pill ${r.champion || r.reached === "Goal met" ? "complete" : ""}">${sourceLabel[r.source]}</span>
      <span><b>${esc(r.reached)}</b><small>${r.record.join("-")} · ${r.gf}–${r.ga} · ${esc(r.formation)}${r.star ? ` · star ${esc(r.star)}` : ""}</small></span>
      <span class="pf-when">${esc(when(r.at))}</span></a>`).join("")}</section>`;
}

function render(p) {
  $("pfhero").innerHTML = `<div class="kicker">Profile · since ${esc(when(p.member_since))}</div>
    <h1 class="arch-h">${esc(p.username)}</h1>${tiles(p)}`;
  $("pfbody").innerHTML = `<div class="cup-grid pf-grid">
    <div class="cup-stack">${recentHtml(p)}</div>
    <div class="cup-stack">${finishesHtml(p)}</div></div>
    <h2 class="h2">Your players</h2><p class="sub">Across every saved tournament and daily challenge.</p>
    <div class="an-boards">
      ${boardHtml("Goals", p.boards.goals, (v) => v)}
      ${boardHtml("Assists", p.boards.assists, (v) => v)}
      ${boardHtml("Most picked", p.boards.picked, (v) => v)}
      ${boardHtml("Average mark", p.boards.mark, (v) => v.toFixed(2), `${p.min_apps_for_mark}+ apps`)}
    </div>`;
}

function signedOut() {
  $("pfhero").innerHTML = `<div class="kicker">Profile</div><h1 class="arch-h">Your nights</h1>`;
  $("pfbody").innerHTML = `<section class="panel gate"><div><h2>Sign in to see your profile</h2>
    <p>Saved tournaments, titles, your daily streak and the players who carried you.</p></div>
    <div class="gate-cta"><button class="btn primary" id="gin">Sign in</button><button class="btn ghost" id="gup">Create an account</button></div></section>`;
  $("gin").onclick = () => openAuth("in");
  $("gup").onclick = () => openAuth("up");
}

onAuth(async (me) => {
  if (!me) return signedOut();
  try { render(await api("/api/profile")); }
  catch (e) { $("pfbody").innerHTML = `<p class="sub">${esc(e.message)}</p>`; }
});
