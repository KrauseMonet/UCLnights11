"use strict";
/* The tournament is a pure function of the draft state, so the server plays all of it
   at once; the page reveals your matches one at a time and keeps the rest of the draw
   back until you have seen your own run, so nothing is spoiled.

   The same page shows a room's tournament (/cup?room=CODE): there every friend's eleven
   is a side, the "Friends" table ranks them, and someone without a seat sees it all at
   once as a spectator. */

const ROOM = new URLSearchParams(location.search).get("room");
shell(ROOM ? "friends" : "draft");
let CUP = null;

const sideName = (s) => s.you ? "Your XI" : s.club;
const sideSub = (s) => s.you ? CUP.you.formation : s.season;
// A short name for tables: a real side carries its season, a friend's eleven its owner.
const tag = (s) => s.you ? "Your XI" : s.human ? s.club : `${s.club} ${s.season.slice(2)}`;

function stageLabel(f) {
  return f.stage === "Group stage" ? `Group ${f.group} · ${f.label}` : `${f.stage} · ${f.label}`;
}

function outcome(f) {
  const home = f.home.you;
  if (f.pens) return (home ? f.pens[0] > f.pens[1] : f.pens[1] > f.pens[0]) ? "w" : "l";
  const mine = home ? f.hg : f.ag, theirs = home ? f.ag : f.hg;
  return mine > theirs ? "w" : mine < theirs ? "l" : "d";
}

function extraLine(f) {
  if (f.pens) return `${f.pens[0]}–${f.pens[1]} pens`;
  return f.extra_time ? "a.e.t." : "";
}

// --------------------------------------------------------------- hero and actions

function renderHero() {
  const done = CUP.revealed >= CUP.your_matches.length;
  const where = CUP.room ? `Room ${esc(CUP.room.code)} · ${esc(CUP.room.format)} · ` : "";
  if (!CUP.you) return renderSpectator(where);
  const avg = Math.round(CUP.you.xi.reduce((a, c) => a + c.rating, 0) / 11);
  // Your eleven, its bench and plan live on the squad page now (C44), one tap away.
  const squad = ROOM ? `/squad?room=${esc(ROOM)}` : `/squad#${esc(CUP.state)}`;
  const kicker = `<div class="kicker">${where}Your XI · ${esc(CUP.you.formation)} · average ${avg}</div>`;
  const squadLink = `<p class="cup-link"><a href="${squad}">Your squad and ratings</a></p>`;
  if (!done) {
    const next = CUP.your_matches[CUP.revealed];
    $("hero").innerHTML = `${kicker}<h1>Your campaign</h1><p>Next: ${esc(stageLabel(next))}</p>${squadLink}`;
    $("actions").innerHTML = `<button class="btn primary" id="play">Play the match</button>${skipButtons(next, "Skip this match")}`;
    $("play").onclick = playNext;
    wireSkips((n) => {
      // Skipping one match unwatched still says how it went.
      if (n === CUP.revealed + 1) toast(`${resultLine(next)}`);
      reveal(n);
    });
    showPreview(next);
    return;
  }
  const champ = CUP.reached === "Champions";
  $("hero").innerHTML = `${kicker}<h1 class="${champ ? "champ" : ""}">${champ ? "Champions" : esc(CUP.reached)}</h1>
    <p>${champ ? "Your eleven won the whole thing." : `${esc(CUP.champion.name)} lifted the trophy.`}</p>${squadLink}`;
  endActions();
  championBlock();
}

function renderSpectator(where) {
  $("hero").innerHTML = `<div class="kicker">${where}watching</div><h1>The draw</h1>
    <p>${esc(CUP.champion.name)} lifted the trophy.</p>`;
  endActions();
  championBlock();
}

/* The ways past matches without watching them: this one, the rest of the group stage
   (while there is any of it left) and everything. Each reveals the results, never more. */
function skipButtons(f, oneLabel) {
  const groups = f.stage === "Group stage" && groupsEnd() > CUP.revealed + 1;
  return `<button class="btn ghost" id="skipone">${oneLabel}</button>
    ${groups ? `<button class="btn ghost" id="skipgroups">Skip the group stage</button>` : ""}
    <button class="btn ghost" id="skipall">Skip to the end</button>`;
}

// Where your knockout matches begin: after the last group match (all of them, if you went out there).
function groupsEnd() {
  const i = CUP.your_matches.findIndex((f) => f.stage !== "Group stage");
  return i < 0 ? CUP.your_matches.length : i;
}

function wireSkips(go) {
  $("skipone").onclick = () => go(CUP.revealed + 1);
  if ($("skipgroups")) $("skipgroups").onclick = () => go(groupsEnd());
  $("skipall").onclick = () => go(CUP.your_matches.length);
}

function resultLine(f) {
  return `${sideName(f.home)} ${f.hg}–${f.ag} ${sideName(f.away)}${extraLine(f) ? ` (${extraLine(f)})` : ""}`;
}

function endActions() {
  const card = (CUP.journey ? `<button class="btn ghost" id="jcard">Journey card</button>` : "")
    + `<a class="btn ghost" href="${CUP.room ? `/analysis?room=${esc(CUP.room.code)}` : `/analysis#${esc(CUP.state)}`}">Tournament analysis</a>`;
  $("actions").innerHTML = CUP.room
    ? `<a class="btn primary" href="/friends">Play another room</a>${card}<button class="btn ghost" id="copy">Copy link</button>`
    : `<a class="btn primary" href="/">Draft again</a>${card}<button class="btn ghost" id="copy">Copy link</button>`;
  $("copy").onclick = () => copyText(location.href, "Link copied");
  if ($("jcard")) $("jcard").onclick = showJourney;
  if (CUP.you) saveButton();
}

/* Save to profile (C31): the server replays the tournament and keeps its own summary.
   Saving twice is harmless; the button says so once it's done. */
async function saveButton() {
  const source = CUP.room ? "room" : "solo", key = CUP.room ? CUP.room.code : CUP.state;
  $("actions").insertAdjacentHTML("beforeend", `<button class="btn ghost" id="save" disabled>Save to profile</button>`);
  const btn = $("save");
  const mark = () => { btn.textContent = "Saved ✓"; btn.disabled = true; btn.title = "On your profile"; };
  await loadMe();
  if (!ME) {
    btn.disabled = false; btn.textContent = "Sign in to save";
    btn.onclick = () => openAuth("in", "Sign in to keep this tournament on your profile.");
    onAuth((me) => { if (me && $("save")) { $("save").remove(); saveButton(); } });
    return;
  }
  try { if ((await api(`/api/results/saved?source=${source}&key=${encodeURIComponent(key)}`)).saved) return mark(); }
  catch { /* the button still works */ }
  btn.disabled = false;
  btn.onclick = async () => {
    btn.disabled = true;
    try { await api("/api/results", { method: "POST", body: JSON.stringify({ source, key }) }); mark(); toast("Saved to your profile"); }
    catch (e) { btn.disabled = false; toast(e.message); }
  };
}

function showJourney() {
  const y = CUP.you;
  const side = { name: y.you ? "Your XI" : y.name, formation: y.formation, crest: y.crest, human: !!y.human,
    avg: Math.round(y.xi.reduce((a, c) => a + c.rating, 0) / y.xi.length), team: y.team, deep: y.deep, ink: y.ink };
  openJourney(CUP.journey, side, CUP.room ? `ROOM ${CUP.room.code}` : `SEED ${CUP.state.split("-")[0].replace(/^b/, "")}`);
}

function championBlock() {
  const c = CUP.champion;
  $("match").innerHTML = `<div class="champ-block band" style="${teamStyle(c)}">
      <div class="trophy">🏆</div>${sideCrest(c, 104)}
      <div class="label" style="color:var(--team-ink)">Champions</div>
      <div class="champ-name">${c.you ? "Your XI" : esc(c.name).replace(/ (\d{4}–\d{2})$/, ' <span class="nowrap">$1</span>')}</div></div>`;
}

function reveal(n) {
  CUP.revealed = n;
  store.set(`cup:${CUP.state}`, n);
  renderHero();
  renderBody();
}

// --------------------------------------------------------------- the match card

const CUP_LOOK = { name: sideName, sub: sideSub, stage: stageLabel };

function matchCard(f, score, clock) {
  return matchCardHtml(f, score, clock, CUP_LOOK);
}

function showPreview(f) {
  $("match").innerHTML = matchCard(f, "v", f.stage === "Final" ? "Neutral ground" : "Kick-off");
}

function playNext() {
  const f = CUP.your_matches[CUP.revealed];
  $("actions").innerHTML = skipButtons(f, "Skip to full time");
  const finish = playMatch($("match"), f, CUP_LOOK, () => {
    CUP.revealed += 1;
    store.set(`cup:${CUP.state}`, CUP.revealed);
    $("actions").innerHTML = CUP.revealed < CUP.your_matches.length
      ? `<button class="btn primary" id="cont">Next match</button>`
      : `<button class="btn primary" id="cont">See how it ended</button>`;
    $("cont").onclick = () => { renderHero(); renderBody(); };
    renderBody();
  });
  $("match").scrollIntoView({ behavior: "smooth", block: "center" });
  // "Skip to full time" shows this match's result; the others finish it and move on.
  wireSkips((n) => { finish(); if (n > CUP.revealed) reveal(n); });
}

// --------------------------------------------------------------- the body

function resRow(f) {
  const t = (s, side) => `<div class="t ${side}">${side === "h" ? `<span class="nm ${s.you ? "you-name" : ""}">${esc(sideName(s))}</span>${sideCrest(s, 22)}` : `${sideCrest(s, 22)}<span class="nm ${s.you ? "you-name" : ""}">${esc(sideName(s))}</span>`}</div>`;
  return `<details class="res-d"><summary class="res ${outcome(f)}"><div class="tag">${esc(f.stage === "Group stage" ? `Group ${f.group} · MD${f.label.slice(-1)}` : f.stage === "Final" ? "Final" : `${f.stage.replace("Quarter-finals", "QF").replace("Semi-finals", "SF")} · ${f.label.replace(" leg", "")}`)}</div>
    ${t(f.home, "h")}<div class="sc">${f.hg}–${f.ag}${extraLine(f) ? `<small>${extraLine(f)}</small>` : ""}</div>${t(f.away, "a")}</summary>
    ${f.goals.length ? `<div class="res-goals">${f.goals.map((g) => `<span class="${g.side ? "a" : "h"}">${esc(g.scorer)} ${g.minute}'${g.assist ? ` <small>${ASSIST_MARK} ${esc(g.assist)}</small>` : ""}</span>`).join("")}</div>` : ""}
    ${statsHtml(f)}</details>`;
}

function groupHtml(g) {
  return `<div class="gtab"><table><thead><tr><th>Group ${g.name}</th><th>P</th><th>GD</th><th>Pts</th></tr></thead><tbody>${
    g.table.map((r, i) => `<tr class="${r.you ? "you" : r.human ? "friend" : ""} ${i < 2 ? "q" : ""}">
      <td><div class="t">${sideCrest(r, 18)}<span class="nm">${esc(tag(r))}</span></div></td>
      <td>${r.p}</td><td>${r.gf - r.ga > 0 ? "+" : ""}${r.gf - r.ga}</td><td><b>${r.pts}</b></td></tr>`).join("")}</tbody></table></div>`;
}

function roundHtml(r) {
  return `<div><span class="label">${esc(r.stage)}</span>${r.ties.map((t) => {
    const single = t.legs.length === 1, aw = t.winner === t.a.key;
    const sa = single ? t.legs[0].hg : t.agg[0], sb = single ? t.legs[0].ag : t.agg[1];
    const pens = t.legs[t.legs.length - 1].pens;
    const line = (s, n, win) => `<div class="${win ? "" : "lose"}">${sideCrest(s, 18)}<span class="nm ${s.you ? "you-name" : ""}">${esc(tag(s))}</span><b>${n}</b></div>`;
    return `<div class="tie">${line(t.a, sa, aw)}${line(t.b, sb, !aw)}${pens ? `<small>pens ${pens[0]}–${pens[1]}</small>` : ""}</div>`;
  }).join("")}</div>`;
}

function leaderList(rows) {
  return `<ol class="boot">${rows.map((r) => `<li>${sideCrest({ ...r, name: r.side }, 28)}
    <div class="who"><b class="${r.you ? "you-name" : ""}">${esc(r.name)}</b><small>${esc(r.side)}</small></div>
    <span class="n">${r.n}</span></li>`).join("")}</ol>`;
}

function renderBody() {
  const done = CUP.revealed >= CUP.your_matches.length;
  const played = CUP.your_matches.slice(0, CUP.revealed);
  const left = [];
  if (played.length) left.push(`<section class="panel"><div class="panel-h"><span class="label">Your results · tap a match for its stats</span>
    <span class="label">${played.filter((f) => outcome(f) === "w").length}W ${played.filter((f) => outcome(f) === "d").length}D ${played.filter((f) => outcome(f) === "l").length}L</span></div>
    ${played.map(resRow).join("")}</section>`);
  if (done && CUP.players) left.push(friendsHtml());
  if (done) {
    left.push(`<section class="panel"><div class="panel-h"><span class="label">Knockouts</span></div><div class="rounds r${CUP.knockout.length}">${CUP.knockout.map(roundHtml).join("")}</div></section>`);
    if (CUP.groups.length) left.push(`<section class="panel"><div class="panel-h"><span class="label">Group stage</span></div><div class="groups">${CUP.groups.map(groupHtml).join("")}</div></section>`);
  }
  const right = [];
  const others = (CUP.players || []).filter((p) => !p.you);
  if (done && others.length) right.push(`<section class="panel"><div class="panel-h"><span class="label">Their elevens</span>
    <select id="whose" aria-label="Whose eleven">${others.map((p, i) => `<option value="${i}">${esc(p.name)} · ${esc(p.formation)}</option>`).join("")}</select></div>
    <div class="pitch" id="theirpitch"></div></section>`);
  if (done && CUP.journey) right.push(playersPanel(CUP.journey));
  if (done) {
    right.push(`<section class="panel"><div class="panel-h"><span class="label">Top scorers</span></div>${leaderList(CUP.golden_boot)}</section>`);
    right.push(`<section class="panel"><div class="panel-h"><span class="label">Most assists</span></div>${leaderList(CUP.assists)}</section>`);
  }
  $("left").innerHTML = left.join("");
  $("right").innerHTML = right.join("");
  if ($("whose")) {
    const show = () => { const p = others[+$("whose").value]; renderPitch($("theirpitch"), p.slots, p.xi, null); };
    $("whose").onchange = show;
    show();
  }
}

function friendsHtml() {
  return `<section class="panel"><div class="panel-h"><span class="label">Friends</span><span class="label">${esc(CUP.room.format)}</span></div>
    <table class="friends-table"><tbody>${CUP.players.map((p, i) => `<tr class="${p.you ? "you" : ""}">
      <td class="n">${i + 1}</td>
      <td><div class="t">${sideCrest(p, 28)}<div><b class="${p.you ? "you-name" : ""}">${esc(p.name)}</b><small>${esc(p.formation)} · average ${p.avg}</small></div></div></td>
      <td class="reach ${p.reached === "Champions" ? "champ" : ""}">${esc(p.reached)}</td>
      <td class="rec">${p.w}W ${p.d}D ${p.l}L<small>${p.gf}–${p.ga}</small></td></tr>`).join("")}</tbody></table></section>`;
}

(async function boot() {
  loadMeta().catch(() => {});
  const state = ROOM ? `room:${ROOM}` : location.hash.slice(1);
  if (ROOM ? !/^[A-Za-z0-9]{6}$/.test(ROOM) : !/^[\w.-]+$/.test(state)) { location.href = ROOM ? "/friends" : "/draft"; return; }
  try { CUP = await api(ROOM ? `/api/rooms/${ROOM}/tournament` : `/api/tournament/${state}`); }
  catch (e) { $("hero").innerHTML = `<h1>Something went wrong</h1><p>${esc(e.message)}</p>`; return; }
  CUP.state = state;
  CUP.revealed = Math.min(+(store.get(`cup:${state}`) || 0), CUP.your_matches.length);
  renderHero();
  renderBody();
})();
