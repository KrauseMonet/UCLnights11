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
const MINUTE_MS = 55;

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
  const kicker = `<div class="kicker">${where}Your XI · ${esc(CUP.you.formation)} · average ${avg}</div>`;
  if (!done) {
    const next = CUP.your_matches[CUP.revealed];
    $("hero").innerHTML = `${kicker}<h1>Your campaign</h1><p>Next: ${esc(stageLabel(next))}</p>`;
    $("actions").innerHTML = `<button class="btn primary" id="play">Play the match</button>
      <button class="btn ghost" id="skip">Skip to the end</button>`;
    $("play").onclick = playNext;
    $("skip").onclick = () => { reveal(CUP.your_matches.length); };
    showPreview(next);
    return;
  }
  const champ = CUP.reached === "Champions";
  $("hero").innerHTML = `${kicker}<h1 class="${champ ? "champ" : ""}">${champ ? "Champions" : esc(CUP.reached)}</h1>
    <p>${champ ? "Your eleven won the whole thing." : `${esc(CUP.champion.name)} lifted the trophy.`}</p>`;
  endActions();
  championBlock();
}

function renderSpectator(where) {
  $("hero").innerHTML = `<div class="kicker">${where}watching</div><h1>The draw</h1>
    <p>${esc(CUP.champion.name)} lifted the trophy.</p>`;
  endActions();
  championBlock();
}

function endActions() {
  $("actions").innerHTML = CUP.room
    ? `<a class="btn primary" href="/friends">Play another room</a><button class="btn ghost" id="copy">Copy link</button>`
    : `<a class="btn primary" href="/">Draft again</a><button class="btn ghost" id="copy">Copy link</button>`;
  $("copy").onclick = () => navigator.clipboard.writeText(location.href).then(() => toast("Link copied"), () => toast(location.href));
}

function championBlock() {
  const c = CUP.champion;
  $("match").innerHTML = `<div class="champ-block band" style="${teamStyle(c)}">
      <div class="trophy">🏆</div>${sideCrest(c, 104)}
      <div class="label" style="color:var(--team-ink)">Champions</div>
      <div class="fan-year" style="font-size:40px">${c.you ? "Your XI" : esc(c.name)}</div></div>`;
}

function reveal(n) {
  CUP.revealed = n;
  store.set(`cup:${CUP.state}`, n);
  renderHero();
  renderBody();
}

// --------------------------------------------------------------- the match card

function sideHtml(s) {
  return `<div class="side band" style="${teamStyle(s)}">${sideCrest(s, 84)}
    <div><b>${esc(sideName(s))}</b><br><small>${esc(sideSub(s))}</small></div></div>`;
}

function matchCard(f, score, clock) {
  return `<div class="matchcard">
    ${sideHtml(f.home)}
    <div class="mid"><div class="stage-tag">${esc(stageLabel(f))}</div>
      <div class="score" id="sc">${score}</div><div class="clock" id="clk">${clock}</div></div>
    ${sideHtml(f.away)}
    <div class="timebar"><i id="tb"></i></div>
    <div class="feed" id="feed"></div></div>`;
}

function showPreview(f) {
  $("match").innerHTML = matchCard(f, "v", f.stage === "Final" ? "Neutral ground" : "Kick-off");
}

function goalLine(g) {
  const assist = g.assist ? ` <small>(${esc(g.assist)})</small>` : "";
  return g.side === 0
    ? `<div class="h">${esc(g.scorer)}${assist}<span class="m">${g.minute}'</span>⚽</div>`
    : `<div class="a">⚽<span class="m">${g.minute}'</span>${esc(g.scorer)}${assist}</div>`;
}

function playNext() {
  const f = CUP.your_matches[CUP.revealed];
  $("match").innerHTML = matchCard(f, "0–0", "0'");
  $("actions").innerHTML = `<button class="btn ghost" id="fast">Skip this match</button>`;
  $("match").scrollIntoView({ behavior: "smooth", block: "center" });
  const end = f.extra_time ? 120 : 90;
  let minute = 0, h = 0, a = 0, gi = 0;
  const feed = $("feed");
  const finish = () => {
    clearInterval(timer);
    while (gi < f.goals.length) feed.insertAdjacentHTML("beforeend", goalLine(f.goals[gi++]));
    $("sc").textContent = `${f.hg}–${f.ag}`;
    $("clk").textContent = f.pens ? `${f.pens[0]}–${f.pens[1]} on penalties` : f.extra_time ? "After extra time" : "Full time";
    $("tb").style.width = "100%";
    CUP.revealed += 1;
    store.set(`cup:${CUP.state}`, CUP.revealed);
    $("actions").innerHTML = CUP.revealed < CUP.your_matches.length
      ? `<button class="btn primary" id="cont">Next match</button>`
      : `<button class="btn primary" id="cont">See how it ended</button>`;
    $("cont").onclick = () => { renderHero(); renderBody(); };
    renderBody();
  };
  const timer = setInterval(() => {
    minute += 1;
    $("clk").textContent = `${minute}'`;
    $("tb").style.width = `${(minute / end) * 100}%`;
    while (gi < f.goals.length && f.goals[gi].minute <= minute) {
      const g = f.goals[gi++];
      g.side === 0 ? h++ : a++;
      const sc = $("sc");
      sc.textContent = `${h}–${a}`;
      sc.classList.remove("flash"); void sc.offsetWidth; sc.classList.add("flash");
      feed.insertAdjacentHTML("beforeend", goalLine(g));
    }
    if (minute >= end) finish();
  }, MINUTE_MS);
  $("fast").onclick = finish;
}

// --------------------------------------------------------------- the body

function resRow(f) {
  const t = (s, side) => `<div class="t ${side}">${side === "h" ? `<span class="nm ${s.you ? "you-name" : ""}">${esc(sideName(s))}</span>${sideCrest(s, 22)}` : `${sideCrest(s, 22)}<span class="nm ${s.you ? "you-name" : ""}">${esc(sideName(s))}</span>`}</div>`;
  return `<div class="res ${outcome(f)}"><div class="tag">${esc(f.stage === "Group stage" ? `Group ${f.group} · MD${f.label.slice(-1)}` : f.stage === "Final" ? "Final" : `${f.stage.replace("Quarter-finals", "QF").replace("Semi-finals", "SF")} · ${f.label.replace(" leg", "")}`)}</div>
    ${t(f.home, "h")}<div class="sc">${f.hg}–${f.ag}${extraLine(f) ? `<small>${extraLine(f)}</small>` : ""}</div>${t(f.away, "a")}</div>`;
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
  if (played.length) left.push(`<section class="panel"><div class="panel-h"><span class="label">Your results</span>
    <span class="label">${played.filter((f) => outcome(f) === "w").length}W ${played.filter((f) => outcome(f) === "d").length}D ${played.filter((f) => outcome(f) === "l").length}L</span></div>
    ${played.map(resRow).join("")}</section>`);
  if (done && CUP.players) left.push(friendsHtml());
  if (done) {
    left.push(`<section class="panel"><div class="panel-h"><span class="label">Knockouts</span></div><div class="rounds r${CUP.knockout.length}">${CUP.knockout.map(roundHtml).join("")}</div></section>`);
    if (CUP.groups.length) left.push(`<section class="panel"><div class="panel-h"><span class="label">Group stage</span></div><div class="groups">${CUP.groups.map(groupHtml).join("")}</div></section>`);
  }
  const right = [];
  if (CUP.you) right.push(`<section class="panel"><div class="panel-h"><span class="label">Your XI</span><span class="label">${esc(CUP.you.formation)}</span></div>
    <div class="pitch" id="cuppitch"></div></section>`);
  const others = (CUP.players || []).filter((p) => !p.you);
  if (done && others.length) right.push(`<section class="panel"><div class="panel-h"><span class="label">Their elevens</span>
    <select id="whose" aria-label="Whose eleven">${others.map((p, i) => `<option value="${i}">${esc(p.name)} · ${esc(p.formation)}</option>`).join("")}</select></div>
    <div class="pitch" id="theirpitch"></div></section>`);
  if (done) {
    right.push(`<section class="panel"><div class="panel-h"><span class="label">Top scorers</span></div>${leaderList(CUP.golden_boot)}</section>`);
    right.push(`<section class="panel"><div class="panel-h"><span class="label">Most assists</span></div>${leaderList(CUP.assists)}</section>`);
  }
  $("left").innerHTML = left.join("");
  $("right").innerHTML = right.join("");
  if (CUP.you) renderPitch($("cuppitch"), CUP.you.code, CUP.you.xi, null);
  if ($("whose")) {
    const show = () => { const p = others[+$("whose").value]; renderPitch($("theirpitch"), p.code, p.xi, null); };
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
