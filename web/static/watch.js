"use strict";
/* Watching a room's tournament together (C52). Once a room completes, the host kicks off
   and every screen follows one clock: a countdown, every friend's match of the round at
   once, a moment at full time, then the next round. The server says when the watch began
   (t0) and lets each round out as the clock reaches it (game.watch): its pairings at the
   countdown, its results at kick-off, the friends' standings at full time. Where this
   screen is follows from t0 and the server's clock, synced as the turn clock is (the
   cricket site's A119), so no screen waits on another and a late arrival lands on the
   current minute.

   Only the host moves the clock, and only forward. The cup page hands the room to this
   while it is being watched and takes it back, every result shown, when the watch ends. */

const WATCH_POLL_MS = 2000;
const WATCH_MAX_BACKOFF_MS = 20000;
const WATCH_TICK_MS = 100;
const WATCH_LEAD_S = 0.15;            // poll just after a part is due, not just before
const WCLOCK = { offset: 0, rtt: Infinity };
let WS = null;                        // the watch as known here, its rounds merged in
let wPollTimer = null;
let wTicker = null;
let wInflight = null;
let wFailures = 0;
let wDrawn = "";                      // what the screen was last drawn for
let wRun = null;                      // the match on the card: { key, runner }
let wBurstUntil = 0;
let wSel = null;                      // the match chosen to watch this round; null: your own

const WATCH_LOOK = {
  name: (s) => s.you ? "Your XI" : s.club,
  sub: (s) => s.season,               // a friend's formation, a real side's season
  stage: (f) => f.stage === "Final" ? "Final" : `${f.stage} · ${f.label}`,
};

function wNow() { return Date.now() / 1000 + WCLOCK.offset; }

/* Each reply's server_now plus half its round trip, keeping the sample with the shortest
   round trip, since that one carries the least error. */
function wSample(t0, t1, serverTime) {
  const rtt = (t1 - t0) / 1000;
  if (serverTime == null || rtt > WCLOCK.rtt) return;
  WCLOCK.rtt = rtt;
  WCLOCK.offset = serverTime + rtt / 2 - t1 / 1000;
}

// --------------------------------------------------------------- the watch's state

function watchStart(w, t0, t1) {
  WS = { ...w, rounds: [], have: 0 };
  wSample(t0, t1, w.server_now);
  wApply(w);
  $("hero").insertAdjacentHTML("afterend", `<p class="conn" id="wconn" hidden></p>`);
  wTicker = setInterval(wTick, WATCH_TICK_MS);
  wTick();
  wSchedule();
}

function wApply(w) {
  if (w.ended) return watchEnd();
  if (w.unchanged) return;
  for (const k of ["started", "t0", "is_host", "seated", "host", "can_start", "host_wait", "you", "format",
                   "break_s", "minute_s"]) if (k in w) WS[k] = w[k];
  if (w.humans) WS.humans = w.humans;
  if (w.host_wait != null) WS.host_wait_until = wNow() + w.host_wait;
  for (const part of w.parts || []) {
    if (part.n < WS.have) continue;
    const r = WS.rounds[part.round] ||= {};
    if (part.kind === "pairs") Object.assign(r, part);
    else if (part.kind === "results") r.fixtures = part.fixtures;
    else r.standings = part.standings;
    WS.have = part.n + 1;
  }
  wDrawn = "";                                     // redraw on the next tick
}

/* Poll every couple of seconds, and just after the next part is due, so a round's results
   arrive within a moment of its kick-off. */
function wSchedule(ms) {
  clearTimeout(wPollTimer);
  if (!WS || document.hidden) return;
  if (ms == null) {
    ms = WATCH_POLL_MS;
    const r = WS.started && wNext();
    if (r != null) ms = Math.max(50, Math.min(ms, (r - wNow() + WATCH_LEAD_S) * 1000));
  }
  wPollTimer = setTimeout(wPoll, ms);
}

// When the next part comes out: the current round's kick-off or full time.
function wNext() {
  const p = wNow() - WS.t0, r = WS.rounds[WS.rounds.length - 1];
  if (!r) return null;
  const due = [r.kick, r.end].find((x) => x > p);
  return due == null ? null : WS.t0 + due;
}

function wPoll() {
  return wInflight ||= wPollOnce().finally(() => { wInflight = null; });
}

async function wPollOnce() {
  clearTimeout(wPollTimer);
  const q = WS.started ? `?have=${WS.have}&t0=${WS.t0}` : "";
  const t0 = Date.now();
  let w;
  try { w = await api(`/api/rooms/${ROOM}/watch${q}`, { timeout: 8000 }); }
  catch (e) {
    wFailures += 1;
    wConn(`${e.message}. Reconnecting…`);
    return wSchedule(Math.min(WATCH_POLL_MS * 2 ** wFailures, WATCH_MAX_BACKOFF_MS));
  }
  if (wFailures) { wFailures = 0; wConn(null); }
  wSample(t0, Date.now(), w.server_now);
  wApply(w);
  if (WS) wSchedule();
}

function wConn(msg) {
  const el = $("wconn");
  if (!el) return;
  el.hidden = !msg;
  if (msg) el.textContent = msg;
}

async function wPost(path, body) {
  try {
    const t0 = Date.now();
    const w = await api(`/api/rooms/${ROOM}/watch/${path}`, { method: "POST", body: JSON.stringify(body || {}) });
    wSample(t0, Date.now(), w.server_now);
    wApply(w);
    if (WS) wSchedule();
  } catch (e) { toast(e.message); wPoll(); }
}

/* The watch is over: every result can be shown, so the cup page takes the room back. */
async function watchEnd() {
  if (!WS) return;
  WS = null;
  clearInterval(wTicker);
  clearTimeout(wPollTimer);
  $("wconn")?.remove();
  for (let tries = 0; ; tries++) {
    try { CUP = await api(`/api/rooms/${ROOM}/tournament`); break; }
    catch (e) {
      // A screen a moment ahead of the server's clock asks before the end; ask again.
      if (tries >= 5) { $("hero").innerHTML = `<h1>Something went wrong</h1><p>${esc(e.message)}</p>`; return; }
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  CUP.state = `room:${ROOM}`;
  CUP.revealed = CUP.your_matches.length;          // watched together: everything is out
  store.set(`cup:${CUP.state}`, CUP.revealed);
  $("match").innerHTML = "";
  renderHero();
  renderBody();
}

// --------------------------------------------------------------- where the clock is

function wWhere() {
  if (!WS.started) return { phase: "waiting" };
  const p = wNow() - WS.t0;
  let i = -1;
  WS.rounds.forEach((r, k) => { if (r.start <= p) i = k; });
  if (i < 0) return { phase: "waiting", p };       // kicked off; the first round is on its way
  const r = WS.rounds[i];
  if (p < r.kick) return { phase: "countdown", i, r, p, left: Math.ceil(r.kick - p) };
  const minute = Math.floor((p - r.kick) / WS.minute_s);
  if (minute < r.minutes) return { phase: "live", i, r, p, minute };
  return { phase: "after", i, r, p, minute: r.minutes };
}

const wTitle = (r) => r.stage === "League phase" || r.stage === "Group stage" ? r.label : r.stage;
const wSubtitle = (r) => r.stage === "League phase" || r.stage === "Group stage" ? r.stage : r.label === "Final" ? "" : r.label;
const wFirstPhase = (r) => r.stage === "League phase" || r.stage === "Group stage";

// The match this screen shows in round r: the one chosen, your own, or the first.
function wPick(r) {
  const list = r.fixtures || r.pairs;
  if (wSel != null && wSel < list.length) return wSel;
  const k = list.findIndex((f) => f.home.you || f.away.you);
  return k < 0 ? 0 : k;
}

// A fixture's score at a minute of its round, and what its clock reads.
function wScore(f, minute) {
  const end = f.extra_time ? 120 : 90;
  if (minute >= end) return { sc: `${f.hg}–${f.ag}`, clock: f.pens ? `pens ${f.pens[0]}–${f.pens[1]}` : f.extra_time ? "a.e.t." : "FT", over: true };
  const goals = f.goals.filter((g) => g.minute <= minute);
  return { sc: `${goals.filter((g) => g.side === 0).length}–${goals.filter((g) => g.side === 1).length}`, clock: `${minute}'`, over: false };
}

// --------------------------------------------------------------- drawing

function wTick() {
  if (!WS) return;
  const at = wWhere();
  const key = [at.phase, at.i, at.r && !!at.r.fixtures, wStandings(at)?.round, WS.is_host, WS.can_start, wSel].join("|");
  if (key !== wDrawn) { wDrawn = key; wDraw(at); }
  wLive(at);
}

/* The latest standings whose round has reached full time. */
function wStandings(at) {
  if (at.i == null) return null;
  for (let k = at.i; k >= 0; k--) {
    const r = WS.rounds[k];
    if (r.standings && r.end <= at.p) return { round: k, r, rows: r.standings };
  }
  return null;
}

function wDraw(at) {
  const where = `Room ${esc(ROOM)} · ${esc(WS.format || "")} · Watching together`;
  const squad = `<p class="cup-link"><a href="/squad?room=${esc(ROOM)}">${WS.you ? "Your squad and ratings" : "Every squad"}</a></p>`;
  if (at.phase === "waiting") {
    wRun = null;
    const kicked = WS.started;
    $("hero").innerHTML = `<div class="kicker">${where}</div><h1>${kicked ? "Kick-off" : "Watch it together"}</h1>
      <p>${kicked ? "The first round is on its way…" : WS.is_host
        ? "Every friend watches the same matches at the same moment. Kick off when they're here."
        : `Every friend watches the same matches at the same moment. Waiting for ${esc(WS.host || "the host")} to kick off.`}</p>
      <p class="note" id="wwait"></p>${squad}`;
    $("actions").innerHTML = !kicked && WS.can_start ? `<button class="btn primary" id="wkick">Kick off</button>` : "";
    if ($("wkick")) $("wkick").onclick = () => wPost("start");
    $("match").innerHTML = "";
    $("left").innerHTML = wFriendsHtml(WS.humans.map((h) => ({ ...h })), "In this room");
    $("right").innerHTML = "";
    $("more").innerHTML = "";
    return;
  }
  const r = at.r;
  $("hero").innerHTML = `<div class="kicker">${where}</div><h1>${esc(wTitle(r))}</h1>
    <p>${wSubtitle(r) ? `${esc(wSubtitle(r))} · ` : ""}<span id="wstate"></span></p>${squad}`;
  wActions(at);
  wCard(at, true);
  $("left").innerHTML = wRoundHtml(at) + wYourResults(at);
  $("left").querySelectorAll("[data-wk]").forEach((b) => b.onclick = () => { wSel = +b.dataset.wk; wRun = null; wDrawn = ""; });
  const st = wStandings(at);
  $("right").innerHTML = st ? wFriendsHtml(st.rows, `Friends · after ${wTitle(st.r)}${wFirstPhase(st.r) ? "" : ` ${st.r.label === "Final" ? "" : st.r.label.toLowerCase()}`}`) : "";
  $("more").innerHTML = "";
}

/* Only the host can skip, and only forward: to this round's kick-off or full time, past
   the league phase, or to the end. Everyone else is told whose clock it is. */
function wActions(at) {
  if (!WS.is_host) {
    $("actions").innerHTML = `<p class="note">${esc(WS.host || "The host")} controls the clock. Only the host can skip ahead.</p>`;
    return;
  }
  const b = [];
  if (at.phase === "countdown") b.push(`<button class="btn primary" data-skip="kickoff">Kick off now</button>`);
  if (at.phase !== "after") b.push(`<button class="btn ghost" data-skip="fulltime">Skip to full time</button>`);
  if (wFirstPhase(at.r)) b.push(`<button class="btn ghost" data-skip="phase">Skip the ${esc(at.r.stage.toLowerCase())}</button>`);
  b.push(`<button class="btn ghost" data-skip="end">Skip to the end</button>`);
  $("actions").innerHTML = b.join("");
  $("actions").querySelectorAll("[data-skip]").forEach((x) => x.onclick = () => {
    const to = x.dataset.skip;
    if (to === "end" && !confirm("Skip to the end for everyone in the room? Every result will show.")) return;
    wPost("skip", { to, round: at.i, have: WS.have });
  });
}

/* The match card: the pairing before kick-off, the match as it plays, full time after. */
function wCard(at, fresh) {
  const r = at.r, k = wPick(r);
  if (at.phase === "countdown" || !r.fixtures) {
    if (fresh) {
      wRun = null;
      const f = { ...r.pairs[k], stage: r.stage, label: r.label };
      $("match").innerHTML = matchCardHtml(f, "v", at.phase === "countdown" ? "Kick-off" : "Kicking off…", WATCH_LOOK);
    }
    return;
  }
  const f = { ...r.fixtures[k], stage: r.stage, label: r.label };
  const key = `${at.i}:${k}`;
  if (!wRun || wRun.key !== key) {
    // A late arrival, a skip or another match chosen: catch up quietly to the minute.
    wRun = { key, runner: matchRunner($("match"), f, WATCH_LOOK) };
    wRun.runner.to(at.minute, false);
  }
  if (at.phase === "after") wRun.runner.whistle();
}

function wLive(at) {
  if (at.phase === "waiting") {
    const left = WS.host_wait_until && !WS.started && !WS.is_host ? Math.ceil(WS.host_wait_until - wNow()) : 0;
    const el = $("wwait");
    if (el) el.textContent = left > 0 ? `If the host hasn't kicked off in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}, anyone in the room can.` : "";
    if (left <= 0 && WS.host_wait_until && !WS.can_start && WS.seated && !WS.started) { WS.host_wait_until = 0; wPoll(); }
    return;
  }
  const r = at.r, state = $("wstate");
  // The match on the card says how far it is; one that ended at 90 in a round allowed
  // 120 (extra time came elsewhere, or could have) is at full time.
  const over = at.phase === "after" || (wRun && wRun.runner.over);
  if (state) state.textContent = at.phase === "countdown" ? `kick-off in ${at.left}` : over ? "full time" : `live, ${at.minute}'`;
  if (r.fixtures && at.phase !== "countdown") {
    if (wRun) {
      if (wRun.runner.to(at.minute).length) wBurstUntil = Date.now() + GOAL_PAUSE_MS;
      if (wBurstUntil && Date.now() > wBurstUntil) { wBurstUntil = 0; $("match").querySelector(".goal-burst")?.remove(); }
    }
    r.fixtures.forEach((f, k) => {
      const s = wScore(f, at.minute), sc = $(`wsc${k}`), ck = $(`wck${k}`);
      if (sc) sc.textContent = s.sc;
      if (ck) ck.textContent = s.clock;
    });
  } else if (at.phase === "countdown") {
    r.pairs.forEach((_, k) => { const ck = $(`wck${k}`); if (ck) ck.textContent = `${at.left}s`; });
  }
}

/* Every friend's match this round, each a button that puts it on the card. */
function wRoundHtml(at) {
  const r = at.r, list = r.fixtures || r.pairs, sel = wPick(r);
  if (list.length < 2) return "";
  const side = (s, cls) => `<div class="t ${cls}">${cls === "h" ? `<span class="nm ${s.you ? "you-name" : ""}">${esc(WATCH_LOOK.name(s))}</span>${sideCrest(s, 22)}` : `${sideCrest(s, 22)}<span class="nm ${s.you ? "you-name" : ""}">${esc(WATCH_LOOK.name(s))}</span>`}</div>`;
  return `<section class="panel"><div class="panel-h"><span class="label">Around the room · tap a match to watch it</span>
      <span class="label">${list.length} matches</span></div>
    ${list.map((f, k) => `<button class="res wt-row ${k === sel ? "on" : ""}" data-wk="${k}" aria-pressed="${k === sel}">
      <div class="tag" id="wck${k}">–</div>${side(f.home, "h")}<div class="sc" id="wsc${k}">v</div>${side(f.away, "a")}</button>`).join("")}</section>`;
}

/* Your results so far: rounds that have reached full time. */
function wYourResults(at) {
  const done = WS.rounds.filter((r, k) => r.fixtures && (k < at.i || (k === at.i && at.phase === "after")))
    .flatMap((r) => r.fixtures.filter((f) => f.home.you || f.away.you).map((f) => ({ ...f, stage: r.stage, label: r.label })));
  if (!done.length) return "";
  return `<section class="panel"><div class="panel-h"><span class="label">Your results · tap a match for its stats</span>
    <span class="label">${done.filter((f) => outcome(f) === "w").length}W ${done.filter((f) => outcome(f) === "d").length}D ${done.filter((f) => outcome(f) === "l").length}L</span></div>
    ${done.map(resRow).join("")}</section>`;
}

/* The friends, after the latest round to reach full time: league place and points while
   the league phase is played, then who is still in it. */
function wFriendsHtml(rows, title) {
  const played = rows.some((x) => x.p);
  const sorted = [...rows].sort((a, b) => (!!a.out - !!b.out) || ((a.pos ?? 99) - (b.pos ?? 99))
    || ((b.pts ?? 0) - (a.pts ?? 0)) || (((b.gf ?? 0) - (b.ga ?? 0)) - ((a.gf ?? 0) - (a.ga ?? 0))));
  return `<section class="panel"><div class="panel-h"><span class="label">${esc(title)}</span></div>
    <table class="friends-table"><tbody>${sorted.map((x) => `<tr class="${x.you ? "you" : ""}">
      <td class="n">${x.pos ?? ""}</td>
      <td><div class="t">${sideCrest(x, 28)}<div><b class="${x.you ? "you-name" : ""}">${esc(x.name)}</b><small>${esc(x.season)}</small></div></div></td>
      ${played ? `<td class="reach ${x.out === "Champions" ? "champ" : ""}">${x.out ? esc(x.out === "Champions" ? "Champions" : `Out · ${x.out}`) : x.pos != null ? `${x.pts} pts` : "Still in"}</td>
      <td class="rec">${x.w}W ${x.d}D ${x.l}L<small>${x.gf}–${x.ga}</small></td>` : ""}</tr>`).join("")}</tbody></table></section>`;
}

document.addEventListener("visibilitychange", () => {
  if (!WS) return;
  if (document.hidden) clearTimeout(wPollTimer);
  else { wDrawn = ""; wRun = null; wPoll(); }
});
