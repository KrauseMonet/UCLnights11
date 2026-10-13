"use strict";
/* The daily challenge (C32): today's eleven squads, the same for everyone; one match
   against a real side; a goal to reach in it. One ranked attempt a day for an account.
   Signed out, the match is a practice one on a different seed, kept nowhere.

   The draft so far is kept in this browser (localStorage), so a reload carries on; the
   server replays it on every request, as the solo draft does. /daily#YYYY-MM-DD shows
   a past day. A bench day's team sheet (C44, here since C55) is kept the same way, and
   so is everything else under a key naming the day's edition: an admin can make a day
   again, and picks from the old edition would replay into other squads. */

shell("daily");
const DAY_IN = /^\d{4}-\d{2}-\d{2}$/.test(location.hash.slice(1)) ? location.hash.slice(1) : null;
let D = null;            // GET /api/daily
let MOVES = [];
let S = null;            // the draft session
let PLAN = null;         // a bench day's plan (C42), chosen here and sent with the match; null: automatic
let SHEET = null;        // a bench day's team sheet (C55): pick indices, the eleven in slot order then the bench; null: as drafted
const dayKey = () => D.challenge.edition ? `${D.challenge.day}:${D.challenge.edition}` : D.challenge.day;
const movesKey = () => `daily:${dayKey()}`;
const planKey = () => `daily:plan:${dayKey()}`;
const sheetKey = () => `daily:sheet:${dayKey()}`;
const sheetText = () => SHEET ? "s" + SHEET.map((i) => i.toString(36)).join("") : "";
function forget() {
  MOVES = []; PLAN = null; SHEET = null;
  store.set(movesKey(), ""); store.set(planKey(), ""); store.set(sheetKey(), "");
}
const NUMBER = { 11: "eleven", 14: "fourteen" };
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
        <small>Draft a ${esc(c.formation.label)} from today's ${NUMBER[c.squads]} squads${c.bench ? ", the last three for your bench" : ""}. No rerolls, and no ratings: pick on what you remember.</small></div>
    </div>
    <p class="sub dl-meta">${D.board.entries} played today${D.board.entries ? ` · ${D.board.met} met the goal` : ""} ·
      a drafter who could see every rating and took the best player each deal reaches it ${c.success_rate}% of the time.
      ${D.streak ? `· Your streak: <b>${D.streak.current}</b> ${D.streak.current === 1 ? "day" : "days"}` : ""}</p>`;
}

function opponentHtml() {
  const o = D.challenge.opponent;
  return `<section class="panel"><div class="panel-h"><span class="label">${esc(o.name)}'s eleven</span><span class="label">${esc(o.shape)}</span></div>
    <ol class="dl-xi">${o.xi.map((c) => `<li>${posChip(c.slot || c.positions[0])}<b>${esc(c.name)}</b>${c.rating == null ? "" : rate(c.rating)}</li>`).join("")}</ol></section>`;
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

const draftUrl = (moves) => `/api/daily/draft?moves=${moves}&edition=${D.challenge.edition}`;

async function loadDraft() {
  try { S = await api(`${draftUrl(movesText())}${SHEET ? `&sheet=${sheetText()}` : ""}${D.today ? "" : `&day=${D.challenge.day}`}`); }
  catch (e) {
    if (e.status === 409) { await boot(); throw e; }   // an admin made the day again: start on the new one
    forget();                                          // a stale draft from another day or version
    S = await api(draftUrl(""));
  }
}

/* The day changed under the page (C55): say so and show the new one. */
function changed(e) {
  if (e.status !== 409) return false;
  toast(e.message);
  boot();
  return true;
}

async function startDraft() {
  try { await loadDraft(); } catch { return; }
  renderDraft(false);
}

function renderDraft(fresh) {
  if (S.complete) return renderReady();
  const forBench = S.picks.length >= 11;
  $("dlbody").innerHTML = `<div class="draft-top"><h2 class="h2 tight">${esc(S.formation.label)}</h2>
      <div class="progress"><span class="label">Pick <b>${S.picks.length + 1}</b> of ${S.total} · no rerolls · <span class="memtag">ratings hidden</span></span>
        <div class="bar"><i style="width:${(S.picks.length / S.total) * 100}%"></i></div></div>
      <div class="linechips" id="lines"></div></div>
    <div class="draft-grid">
      <section class="panel deal" id="deal" aria-live="polite"></section>
      <aside class="cup-stack"><section class="panel"><div class="panel-h"><span class="label">Your XI</span>
          <span class="label">${S.bench_size ? `${S.xi.length} / 11 · bench ${S.bench.length} / ${S.bench_size}` : `${S.picks.length} / 11`}</span></div>
        <div class="pitch" id="pitch"></div><div class="bench-row" id="bench" hidden></div></section>${opponentHtml()}</aside></div>`;
  lineChips($("lines"), S.formation, S.xi);
  renderDeal($("deal"), S.deal, {
    heading: forBench ? `For your bench · squad ${S.picks.length + 1} of ${S.total}` : `Squad ${S.picks.length + 1} of ${S.total}`,
    takeLabel: forBench ? "Bench" : undefined, fresh, onTake: take,
  });
  renderPitch($("pitch"), S.formation.slots, S.xi, S.picks.length && !forBench ? S.picks[S.picks.length - 1].id : null);
  renderBench($("bench"), S.bench, S.bench_size);
  pitchPeek($("pitch"), S);
}

let busy = false;
async function take(i) {
  if (busy) return;
  busy = true;
  try {
    const next = [...MOVES, i];
    S = await api(draftUrl(next.join(".")));
    MOVES = next;
    store.set(movesKey(), movesText());
    renderDraft(true);
  } catch (e) { dropFlight(); if (!changed(e)) toast(e.status === 0 ? `${e.message}. Your picks are safe; try again.` : e.message); }
  finally { busy = false; }
}

function playButtons(signedIn) {
  return `<button class="btn primary" id="go">${signedIn ? "Play the ranked match" : "Play a practice match"}</button>
    ${signedIn ? "" : `<button class="btn ghost" id="sign">Sign in</button>`}
    <button class="btn ghost" id="redo">Start the draft again</button>`;
}

function wireReady() {
  $("go").onclick = play;
  $("redo").onclick = () => {
    if (!confirm("Throw this squad away and draft again?")) return;
    forget(); startDraft();
  };
  if ($("sign")) $("sign").onclick = () => openAuth("in", "Sign in to take today's ranked attempt.");
}

/* A bench day (C42): the team sheet and the plan, then the match. Both are kept here like
   the picks, and sent with them. */
function renderPlanReady() {
  const signedIn = !!ME;
  // A plan kept from before can only name substitutes and starters this squad has.
  if (PLAN) PLAN = PLAN.filter((x) => S.bench[x.on]).map((x) =>
    ({ ...x, off: x.off != null && S.bench[x.on].can_replace.includes(x.off) ? x.off : null }));
  if (!$("plan")) {
    $("dlbody").innerHTML = `<div class="draft-grid">
      <section class="panel deal" id="plan"></section>
      <aside class="cup-stack"><section class="panel"><div class="panel-h"><span class="label">Your XI</span><span class="label">${esc(S.formation.label)}</span></div>
        <div class="pitch" id="pitch"></div><div class="bench-row" id="bench" hidden></div></section>${opponentHtml()}</aside></div>`;
  }
  planPanel($("plan"), S, PLAN || S.plan, {
    tag: PLAN ? "your plan" : "automatic plan",
    onChange: (p) => { PLAN = p; store.set(planKey(), JSON.stringify(p)); renderPlanReady(); },
    foot: `${playButtons(signedIn)}
      <p class="label">${signedIn ? "One go, ranked. Once you play, today's attempt is used." :
        "Signed out, this is a practice match on a different seed, not ranked. Sign in before you play to be ranked."} ${AUTO_NOTE}</p>`,
  });
  renderPitch($("pitch"), S.formation.slots, S.xi, null);
  renderBench($("bench"), S.bench, S.bench_size);
  // The team sheet (C44, C55): worked out by the server, kept here; a plan follows its men.
  if (!$("sheethint")) $("bench").insertAdjacentHTML("afterend", `<p class="sheet-hint" id="sheethint"></p>`);
  sheetEditor($("pitch"), $("bench"), S, {
    hint: $("sheethint"), onMove: (man, to) => postSheet({ man, to }), reset: SHEET ? () => postSheet({}) : null,
  });
  wireReady();
}

async function postSheet(body) {
  if (busy) return;
  busy = true;
  try {
    const before = S;
    S = await api("/api/daily/sheet", { method: "POST", body: JSON.stringify({
      moves: movesText(), current: SHEET, edition: D.challenge.edition, ...body }) });
    SHEET = S.sheet;
    if (PLAN) PLAN = carryPlan(PLAN, before, S);
    store.set(sheetKey(), SHEET ? JSON.stringify(SHEET) : "");
    store.set(planKey(), PLAN ? JSON.stringify(PLAN) : "");
  } catch (e) { if (changed(e)) return; toast(e.message); } finally { busy = false; }
  renderPlanReady();
}

function renderReady() {
  if (S.bench_size) return renderPlanReady();
  const signedIn = !!ME;
  $("dlbody").innerHTML = `<div class="friends-grid">
    <section class="panel gate"><div><h2>Your eleven is in</h2>
      <p>${signedIn ? "<b>One go, ranked.</b> Once you play, today's attempt is used." :
        "You're signed out, so this is a <b>practice</b> match on a different seed, and it won't be ranked. Sign in <b>before you play</b> to take today's ranked attempt."}</p></div>
      <div class="gate-cta">${playButtons(signedIn)}</div></section>
    <aside class="panel"><div class="panel-h"><span class="label">Your XI</span><span class="label">${esc(S.formation.label)}</span></div>
      <div class="pitch" id="pitch"></div></aside></div>`;
  renderPitch($("pitch"), S.formation.slots, S.xi, null);
  wireReady();
}

// ---------------------------------------------------------------- the match and after

async function play() {
  $("go").disabled = true;
  let out;
  try {
    out = await api(ME ? "/api/daily/submit" : "/api/daily/practice", { method: "POST", body: JSON.stringify({
      moves: movesText(), changes: S.bench_size ? PLAN : null, sheet: S.bench_size ? SHEET : null,
      edition: D.challenge.edition }) });
  } catch (e) {
    toast(e.message);
    if (e.status === 409) return boot();             // already played in another tab, or the day was made again
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
      <p>${NUMBER[D.challenge.squads][0].toUpperCase() + NUMBER[D.challenge.squads].slice(1)} squads, dealt the same to everyone. Take one player from each into your ${esc(D.challenge.formation.label)}${D.challenge.bench ? ", the last three onto your bench, then set who starts where and plan your changes" : ""}. No rerolls,
        and <b>every rating is hidden</b>, the opponent's too, until you've played. ${ME ? "Then one ranked match." : "Signed out, the match is practice; sign in first to be ranked."}</p></div>
      <div class="gate-cta"><button class="btn primary" id="start">${MOVES.length ? `Continue (${MOVES.length} of ${D.challenge.squads})` : "Start the draft"}</button>
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
  try { PLAN = JSON.parse(store.get(planKey()) || "null"); } catch { PLAN = null; }
  try { SHEET = JSON.parse(store.get(sheetKey()) || "null"); } catch { SHEET = null; }
  if (D.mine) return showPlayed();
  if (!D.today) return showPast();
  intro();
}

onAuth(() => boot());
