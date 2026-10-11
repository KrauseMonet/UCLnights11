"use strict";
/* The daily challenge (C32): today's eleven squads, the same for everyone; one match
   against a real side; a goal to reach in it. One ranked attempt a day for an account.
   Signed out, the match is a practice one on a different seed, kept nowhere.

   The draft so far is kept in this browser (localStorage), so a reload carries on; the
   server replays it on every request, as the solo draft does. /daily#YYYY-MM-DD shows
   a past day. */

shell("daily");
const DAY_IN = /^\d{4}-\d{2}-\d{2}$/.test(location.hash.slice(1)) ? location.hash.slice(1) : null;
let D = null;            // GET /api/daily
let MOVES = [];
let S = null;            // the draft session
const movesKey = () => `daily:${D.challenge.day}`;
const movesText = () => MOVES.join(".");
const fmtDay = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });

const DAILY_LOOK = {
  name: (s) => s.you ? "Your XI" : s.club,
  sub: (s) => s.you ? D.challenge.formation.label : s.season,
  stage: () => `Daily · ${D.challenge.goal}`,
};

// ---------------------------------------------------------------- the day

function heroHtml() {
  const c = D.challenge, o = c.opponent;
  return `<div class="kicker">Daily challenge · ${esc(fmtDay(c.day))}${D.today ? "" : " · a past day"}</div>
    <h1 class="arch-h">${esc(c.goal)} <em>against ${esc(o.club)}</em></h1>
    <div class="dl-card band" style="${teamStyle(o)}">
      ${crest(o.crest, 84, o.name)}
      <div class="dl-opp"><span class="label">The opponent · ${esc(o.shape)}</span><b>${esc(o.name)}</b>
        <small>Ninety minutes on neutral ground. No extra time, no penalties.</small></div>
      <div class="dl-goal"><span class="label">Your goal</span><b>${esc(c.goal)}</b>
        <small>Draft a ${esc(c.formation.label)} from today's eleven squads. No rerolls, and no ratings: pick on what you remember.</small></div>
    </div>
    <p class="sub dl-meta">${D.board.entries} played today${D.board.entries ? ` · ${D.board.met} met the goal` : ""} ·
      a drafter who could see every rating and took the best player each deal reaches it ${c.success_rate}% of the time.
      ${D.streak ? `· Your streak: <b>${D.streak.current}</b> ${D.streak.current === 1 ? "day" : "days"}` : ""}</p>`;
}

function opponentHtml() {
  const o = D.challenge.opponent;
  return `<section class="panel"><div class="panel-h"><span class="label">${esc(o.name)}'s eleven</span><span class="label">${esc(o.shape)}</span></div>
    <ol class="dl-xi">${o.xi.map((c) => `<li><span class="pos ${c.pos}">${c.pos}</span><b>${esc(c.name)}</b>${c.rating == null ? "" : rate(c.rating)}</li>`).join("")}</ol></section>`;
}

function boardHtml(b) {
  if (!b.rows.length) return `<section class="panel"><div class="panel-h"><span class="label">Today's table</span></div>
    <p class="empty">Nobody has played yet. Be the first.</p></section>`;
  return `<section class="panel"><div class="panel-h"><span class="label">${D.today ? "Today's" : "That day's"} table</span>
      <span class="label">${b.entries} played${b.mine ? ` · you're #${b.mine.rank}` : ""}</span></div>
    <table class="an-table dl-board"><thead><tr><th>#</th><th>Player</th><th>Goal</th><th>Score</th><th title="The eleven's average mark">Mark</th></tr></thead>
    <tbody>${b.rows.map((r) => `<tr class="${r.you ? "you" : ""}"><td>${r.rank}</td><td>${esc(r.username)}</td>
      <td>${r.met ? "✅" : "❌"}</td><td>${r.gf}–${r.ga}</td><td>${r.mark == null ? "–" : r.mark.toFixed(2)}</td></tr>`).join("")}</tbody></table>
    <p class="note dl-note">Ranked by the goal, then goal difference, goals scored, the eleven's average mark, and who played first.</p></section>`;
}

// ---------------------------------------------------------------- the draft

async function loadDraft() {
  try { S = await api(`/api/daily/draft?moves=${movesText()}${D.today ? "" : `&day=${D.challenge.day}`}`); }
  catch (e) {                                      // a stale draft from another day or version
    MOVES = []; store.set(movesKey(), "");
    S = await api(`/api/daily/draft?moves=`);
  }
}

async function startDraft() {
  await loadDraft();
  renderDraft(false);
}

function renderDraft(fresh) {
  if (S.complete) return renderReady();
  $("dlbody").innerHTML = `<div class="draft-top"><h2 class="h2 tight">${esc(S.formation.label)}</h2>
      <div class="progress"><span class="label">Pick <b style="color:var(--gold)">${S.picks.length + 1}</b> of 11 · no rerolls · <span class="memtag">ratings hidden</span></span>
        <div class="bar"><i style="width:${(S.picks.length / 11) * 100}%"></i></div></div>
      <div class="linechips" id="lines"></div></div>
    <div class="draft-grid">
      <section class="panel deal" id="deal" aria-live="polite"></section>
      <aside class="cup-stack"><section class="panel"><div class="panel-h"><span class="label">Your XI</span><span class="label">${S.picks.length} / 11</span></div>
        <div class="pitch" id="pitch"></div></section>${opponentHtml()}</aside></div>`;
  lineChips($("lines"), S.formation, S.picks);
  renderDeal($("deal"), S.deal, { heading: `Squad ${S.picks.length + 1} of 11`, fresh, onTake: take });
  renderPitch($("pitch"), S.formation.code, S.picks, S.picks.length ? S.picks[S.picks.length - 1].id : null);
}

let busy = false;
async function take(i) {
  if (busy) return;
  busy = true;
  try {
    const next = [...MOVES, i];
    S = await api(`/api/daily/draft?moves=${next.join(".")}`);
    MOVES = next;
    store.set(movesKey(), movesText());
    renderDraft(true);
  } catch (e) { toast(e.status === 0 ? `${e.message}. Your picks are safe; try again.` : e.message); }
  finally { busy = false; }
}

function renderReady() {
  const signedIn = !!ME;
  $("dlbody").innerHTML = `<div class="friends-grid">
    <section class="panel gate"><div><h2>Your eleven is in</h2>
      <p>${signedIn ? "<b>One go, ranked.</b> Once you play, today's attempt is used." :
        "You're signed out, so this is a <b>practice</b> match on a different seed, and it won't be ranked. Sign in <b>before you play</b> to take today's ranked attempt."}</p></div>
      <div class="gate-cta"><button class="btn primary" id="go">${signedIn ? "Play the ranked match" : "Play a practice match"}</button>
        ${signedIn ? "" : `<button class="btn ghost" id="sign">Sign in</button>`}
        <button class="btn ghost" id="redo">Start the draft again</button></div></section>
    <aside class="panel"><div class="panel-h"><span class="label">Your XI</span><span class="label">${esc(S.formation.label)}</span></div>
      <div class="pitch" id="pitch"></div></aside></div>`;
  renderPitch($("pitch"), S.formation.code, S.picks, null);
  $("go").onclick = play;
  $("redo").onclick = () => { if (confirm("Throw this eleven away and draft again?")) { MOVES = []; store.set(movesKey(), ""); startDraft(); } };
  if ($("sign")) $("sign").onclick = () => openAuth("in", "Sign in to take today's ranked attempt.");
}

// ---------------------------------------------------------------- the match and after

async function play() {
  $("go").disabled = true;
  let out;
  try {
    out = await api(ME ? "/api/daily/submit" : "/api/daily/practice", { method: "POST", body: JSON.stringify({ moves: movesText() }) });
  } catch (e) {
    toast(e.message);
    if (e.status === 409) return boot();             // already played, in another tab
    $("go").disabled = false;
    return;
  }
  $("dlbody").innerHTML = `<div id="match"></div><div class="cup-actions" id="dlact"><button class="btn ghost" id="fast">Skip to full time</button></div><div id="after"></div>`;
  const finish = playMatch($("match"), out.fixture, DAILY_LOOK, () => {
    $("dlact").innerHTML = "";
    if (out.ranked) { D.mine = out; D.board = out.board; D.streak = out.streak; D.challenge.opponent = out.opponent; }
    $("after").innerHTML = afterHtml(out);
    wireAfter(out);
  });
  $("match").scrollIntoView({ behavior: "smooth", block: "center" });
  $("fast").onclick = finish;
}

function shareLine(out) {
  const c = D.challenge, b = D.board;
  const lines = [`UCLnights11 daily · ${c.day}`, `${c.goal} v ${c.opponent.club} ${c.opponent.season}`,
    `${out.met ? "✅ Goal met" : "❌ Goal missed"} · ${out.gf}–${out.ga}`];
  if (b && b.mine) lines.push(`#${b.mine.rank} of ${b.entries}${D.streak && D.streak.current > 1 ? ` · 🔥 ${D.streak.current} days` : ""}`);
  lines.push(`${location.origin}/daily`);
  return lines.join("\n");
}

function afterHtml(out) {
  const mine = D.board && D.board.mine;
  return `<section class="dl-verdict ${out.met ? "met" : "missed"}">
      <div class="dl-v-mark" aria-hidden="true">${out.met ? "✓" : "✕"}</div>
      <div><h2>${out.met ? "Goal met" : "Goal missed"}</h2>
        <p>${esc(D.challenge.goal)}: you finished ${out.gf}–${out.ga}.
          ${out.ranked && mine ? `You're <b>#${mine.rank}</b> of ${D.board.entries} today.` : out.ranked ? "" : "A practice match, not ranked."}
          ${out.ranked && D.streak ? ` Streak: <b>${D.streak.current}</b> ${D.streak.current === 1 ? "day" : "days"} (best ${D.streak.best}).` : ""}</p></div>
      <div class="dl-v-acts">${out.ranked ? `<button class="btn primary" id="share">Share</button>` : ""}
        ${out.fixture ? `<button class="btn ghost" id="again">Watch it again</button>` : ""}
        ${out.ranked ? `<a class="btn ghost" href="/profile">Profile</a>` : `<button class="btn ghost" id="sign2">Sign in for tomorrow</button>`}</div>
    </section>
    <div class="cup-grid">
      <div class="cup-stack">${out.ranked ? boardHtml(D.board) : ""}</div>
      <div class="cup-stack">${out.journey ? playersPanel(out.journey) : ""}${opponentHtml()}</div>
    </div>`;
}

function wireAfter(out) {
  if ($("share")) $("share").onclick = () => {
    const text = shareLine(out);
    if (navigator.share && matchMedia("(pointer: coarse)").matches) navigator.share({ text }).catch(() => {});
    else (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(() => toast("Copied: paste it anywhere"), () => toast(text));
  };
  if ($("again")) $("again").onclick = () => {
    playMatch($("match"), out.fixture, DAILY_LOOK, () => {});
    $("match").scrollIntoView({ behavior: "smooth", block: "center" });
  };
  if ($("sign2")) $("sign2").onclick = () => openAuth("up", "Create an account and tomorrow's attempt is ranked.");
}

function showPlayed() {
  const out = D.mine;
  $("dlbody").innerHTML = `<div id="match"></div><div id="after"></div>`;
  if (out.fixture) $("match").innerHTML = matchCardHtml(out.fixture, `${out.gf}–${out.ga}`, "Full time", DAILY_LOOK);
  if (out.fixture) $("mstats").innerHTML = statsHtml(out.fixture);
  $("after").innerHTML = afterHtml(out);
  wireAfter(out);
}

function showPast() {
  $("dlbody").innerHTML = `<div class="cup-grid"><div class="cup-stack">${boardHtml(D.board)}</div>
    <div class="cup-stack"><section class="panel gate"><div><h2>You didn't play this day</h2>
      <p>Each day's challenge can only be played on its day.</p></div>
      <div class="gate-cta"><a class="btn primary" href="/daily">Today's challenge</a></div></section>${opponentHtml()}</div></div>`;
}

function intro() {
  $("dlbody").innerHTML = `<div class="cup-grid">
    <div class="cup-stack"><section class="panel gate"><div><h2>${MOVES.length ? "Carry on drafting" : "Draft today's eleven"}</h2>
      <p>Eleven squads, dealt the same to everyone. Take one player from each into your ${esc(D.challenge.formation.label)}. No rerolls,
        and <b>every rating is hidden</b>, the opponent's too, until you've played. ${ME ? "Then one ranked match." : "Signed out, the match is practice; sign in first to be ranked."}</p></div>
      <div class="gate-cta"><button class="btn primary" id="start">${MOVES.length ? `Continue (${MOVES.length} of 11)` : "Start the draft"}</button>
        ${ME ? "" : `<button class="btn ghost" id="sign">Sign in</button>`}</div></section>
      ${boardHtml(D.board)}</div>
    <div class="cup-stack">${opponentHtml()}</div></div>`;
  $("start").onclick = startDraft;
  if ($("sign")) $("sign").onclick = () => openAuth("in", "Sign in to take today's ranked attempt.");
}

async function boot() {
  try { D = await api(`/api/daily${DAY_IN ? `?day=${DAY_IN}` : ""}`); }
  catch (e) {
    $("dlhero").innerHTML = `<div class="kicker">Daily challenge</div><h1 class="arch-h">Not today</h1><p class="sub">${esc(e.message)}</p>`;
    return;
  }
  $("dlhero").innerHTML = heroHtml();
  MOVES = (store.get(movesKey()) || "").split(".").filter((x) => x !== "").map(Number);
  if (D.mine) return showPlayed();
  if (!D.today) return showPast();
  intro();
}

onAuth(() => boot());
