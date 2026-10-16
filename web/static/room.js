"use strict";
/* One room, from lobby to the last pick. The room is polled every few seconds; each
   reply carries a version that only ever goes up, so a slow reply that lands after a
   newer one is dropped instead of rolling the screen back. Your own deal is redrawn
   only when your draft has actually moved, so a poll never interrupts a pick.

   A failed poll is not the end of the room. Phones freeze a tab in the background and
   the first request after waking often fails; the first version of this page treated
   any failure as "Not here" and never repainted, which is how a real room was lost
   (C22). Only a 404 means the room is gone; anything else keeps the screen, says it is
   reconnecting, and tries again with a growing pause. */

shell("friends");
const CODE = location.hash.slice(1).toUpperCase();
const POLL_MS = 2500;
const TURN_POLL_MS = 1000;            // while a pick clock runs, so a turn passes within a second
const MAX_BACKOFF_MS = 20000;
const POLL_TIMEOUT_MS = 8000;         // a poll is asked again soon anyway; don't hang on one for 15 s
const STATUS = { lobby: "Lobby", drafting: "Drafting", complete: "Finished" };
let R = null;              // the room as last applied
let shown = null;          // the draft state the deal on screen belongs to
let busy = false;
let timer = null;
let inflight = null;       // the one poll in flight: a timer, a tab waking and a failed move can all ask at once
let failures = 0;
let dead = false;
let wantsJoin = new URLSearchParams(location.search).has("join");
const TITLE = document.title;

/* The server's clock, as seen from here (the cricket site's A119): each poll's
   server_now plus half its round trip, keeping only the sample with the shortest round
   trip, since that one carries the least error. The countdown reads this, never the
   seconds a reply happened to say. */
const CLOCK = { offset: 0, rtt: Infinity };
function serverNow() { return Date.now() / 1000 + CLOCK.offset; }
function sampleClock(t0, t1, serverTime) {
  const rtt = (t1 - t0) / 1000;
  if (serverTime == null || rtt > CLOCK.rtt) return;
  CLOCK.rtt = rtt;
  CLOCK.offset = serverTime + rtt / 2 - t1 / 1000;
}
const takingTurns = () => R && R.style === "turns" && R.status === "drafting";

const movesIn = (state) => { const p = state.split("-"); return p.length === 3 && p[2] ? p[2].split(".").length : 0; };
const inviteUrl = () => `${location.origin}/room?join=1#${CODE}`;

function apply(room) {
  if (R && room.version < R.version) return;
  const same = R && room.version === R.version && room.seated === R.seated && room.is_host === R.is_host;
  R = room;
  // A finished room shows everyone's squad first (the page marks it seen), then the cup.
  if (R.status === "complete") { location.replace(store.get(`squad:${R.code}`) ? `/cup?room=${R.code}` : `/squad?room=${R.code}`); return; }
  if (!same) render();                               // nothing new: leave the screen alone
  maybeJoin();
}

function schedule(ms = takingTurns() ? TURN_POLL_MS : POLL_MS) {
  clearTimeout(timer);
  if (!dead && !document.hidden) timer = setTimeout(poll, ms);
}

function poll() {
  if (dead) return Promise.resolve();
  return inflight ||= pollOnce().finally(() => { inflight = null; });
}

async function pollOnce() {
  clearTimeout(timer);
  let room;
  const t0 = Date.now();
  // Naming the version on screen lets the server answer "unchanged" in a few bytes.
  const path = R ? `/api/rooms/${CODE}?v=${R.version}` : `/api/rooms/${CODE}`;
  try {
    room = await api(path, { timeout: POLL_TIMEOUT_MS });
    sampleClock(t0, Date.now(), room.unchanged ? room.server_now : room.turns && room.turns.server_now);
  }
  catch (e) {
    if (e.status === 404) return gone(e.message);
    failures += 1;
    connection(e.message);
    return schedule(Math.min(POLL_MS * 2 ** failures, MAX_BACKOFF_MS));
  }
  if (failures) { failures = 0; connection(null); }
  if (!room.unchanged) apply(room);
  schedule();
}

/* The one line that says the room is still there but this browser can't reach it. */
function connection(msg) {
  const el = $("conn");
  el.hidden = !msg;
  if (msg) el.textContent = R ? `${msg}. Reconnecting…` : `${msg}. Trying again…`;
}

function gone(msg) {
  dead = true;
  clearTimeout(timer);
  connection(null);
  $("top").innerHTML = `<div><div class="kicker">Room ${esc(CODE)}</div><h1 class="arch-h">Not here</h1><p class="sub">${esc(msg)}</p></div>`;
  $("strip").innerHTML = "";
  $("view").innerHTML = `<a class="btn primary" href="/friends">Back to friends</a>`;
}

async function act(path, body) {
  if (busy) return;
  busy = true;
  try { apply(await api(`/api/rooms/${CODE}/${path}`, { method: "POST", body: body ? JSON.stringify(body) : undefined })); }
  catch (e) {
    // With no reply the move may still have landed; the poll shows which. A pick sent
    // twice is refused by its `expect`, so asking again can't take a second player. A
    // 409 carries the room as it now is, so the screen catches up at once.
    toast(e.status === 0 ? "Connection dropped. Checking whether that went through…" : e.message);
    if (e.status !== 0) dropFlight();               // refused: he isn't going anywhere
    if (e.status === 409 && e.body && e.body.room) apply(e.body.room);
    else poll();
  }
  finally { busy = false; }
}

async function maybeJoin() {
  if (!wantsJoin || !R || R.seated || R.status !== "lobby" || !ME) return;
  wantsJoin = false;
  history.replaceState(null, "", `/room#${CODE}`);
  await act("join");
}

// ------------------------------------------------------------------ the header and strip

function render() {
  const you = R.seats.find((s) => s.you);
  $("top").innerHTML = `
    <div><div class="kicker">${esc(R.format)} · ${esc(STATUS[R.status] || R.status)}${R.style === "turns" ? ` · take turns, ${R.timer}s` : " · own pace"}${R.bench ? " · bench" : ""}${R.together ? " · watch together" : ""}${R.memory ? " · Memory" : ""}</div>
      <h1 class="room-code" aria-label="Room code ${esc(R.code)}">${esc(R.code)}</h1>
      <p class="sub">${R.seats.length} of ${R.size} players${R.fillers ? ` · ${R.fillers} place${R.fillers === 1 ? "" : "s"} for real sides` : ""}${you ? "" : " · watching"}</p></div>
    <div class="room-acts">${R.status === "lobby" ? `<button class="btn ghost small" id="invite">Copy invite link</button>` : ""}
      <a class="btn ghost small" href="/friends">All rooms</a></div>`;
  const inv = $("invite");
  if (inv) inv.onclick = () => copyText(inviteUrl(), "Invite link copied");
  renderStrip();
  if (R.status === "lobby") renderLobby();
  else if (R.status === "failed") renderFailed();
  else if (planning()) renderPlanning();
  else if (R.style === "turns") renderTurns();
  else renderDrafting();
}

function renderStrip() {
  const kick = R.is_host && R.status === "lobby";
  $("strip").innerHTML = R.seats.map((s) => `
    <div class="seatcard ${s.you ? "me" : ""} ${s.complete && s.ready ? "done" : ""} ${R.turns && R.turns.turn && R.turns.turn.id === s.id ? "on" : ""}" style="${teamStyle(s)}">
      ${sideCrest({ human: true, name: s.username, ...s }, 36)}
      <div class="who"><b>${esc(s.username)}${s.host ? ' <span class="host" title="Host">host</span>' : ""}</b>
        <small>${esc(s.formation)}${R.status === "lobby" ? "" : !s.complete ? ` · ${s.picks}/${R.picks_each}` : !R.bench ? " · eleven in" : s.ready ? " · ready" : " · planning"}</small>
        ${R.status === "drafting" ? `<div class="mini"><i style="width:${(s.picks / R.picks_each) * 100}%"></i></div>` : ""}</div>
      ${kick && !s.you ? `<button class="kick" data-id="${s.id}" aria-label="Remove ${esc(s.username)}">✕</button>` : ""}
    </div>`).join("") + (R.fillers ? `<div class="seatcard ghosted"><span class="crest c36" aria-hidden="true">★</span>
      <div class="who"><b>${R.fillers} real side${R.fillers === 1 ? "" : "s"}</b><small>historical squads</small></div></div>` : "");
  $("strip").querySelectorAll(".kick").forEach((b) => b.onclick = () => act("kick", { account_id: +b.dataset.id }));
}

// ------------------------------------------------------------------ the lobby

function renderLobby() {
  shown = null;
  const you = R.seats.find((s) => s.you);
  if (!you) {
    const full = R.seats.length >= R.size;
    $("view").innerHTML = `<section class="panel gate"><div><h2>${full ? "This room is full" : "You're invited"}</h2>
      <p>${full ? "Every seat is taken. Ask the host for a bigger room next time." : "Join, pick a formation and wait for the host to start the draft."}</p></div>
      <div class="gate-cta">${full ? `<a class="btn ghost" href="/friends">Back to friends</a>`
        : ME ? `<button class="btn primary" id="joinb">Join this room</button>` : `<button class="btn primary" id="sign">Sign in to join</button>`}</div></section>`;
    if ($("joinb")) $("joinb").onclick = () => act("join");
    if ($("sign")) $("sign").onclick = () => { wantsJoin = true; openAuth("in", "Sign in or create an account to take a seat."); };
    return;
  }
  const real = R.fillers;
  $("view").innerHTML = `<div class="friends-grid">
    <section class="panel">
      <div class="panel-h"><span class="label">Your formation</span><span class="label">fixed when the draft starts</span></div>
      <div class="room-form"><div class="chips" id="forms" role="radiogroup" aria-label="Formation"></div>${shapeBox("lobbyshape")}</div>
      <div class="panel-h"><span class="label">The draft</span><span class="label">${R.is_host ? "your call as host" : "the host's call"}</span></div>
      <div class="room-form">${R.is_host
        ? `<div class="chips" role="radiogroup" aria-label="Draft style">
             <button class="chip" role="radio" aria-checked="${R.style === "turns"}" data-style="turns">Take turns · shared pool</button>
             <button class="chip" role="radio" aria-checked="${R.style === "own"}" data-style="own">Own pace</button></div>
           ${R.style === "turns" ? `<div class="chips" role="radiogroup" aria-label="Pick clock">${[15, 30, 45].map((t) =>
             `<button class="chip" role="radio" aria-checked="${R.timer === t}" data-timer="${t}">${t}s a pick</button>`).join("")}</div>` : ""}`
        : `<p class="note">${R.style === "turns" ? `<b>Taking turns</b>, ${R.timer} seconds a pick.` : "<b>Own pace:</b> everyone drafts at once."}</p>`}</div>
      <div class="panel-h"><span class="label">The bench</span><span class="label">${R.is_host ? "your call as host" : "the host's call"}</span></div>
      <div class="room-form">${R.is_host
        ? `<div class="chips" role="radiogroup" aria-label="Bench">
             <button class="chip" role="radio" aria-checked="${R.bench}" data-b="1">Three substitutes</button>
             <button class="chip" role="radio" aria-checked="${!R.bench}" data-b="0">No bench</button></div>`
        : `<p class="note">${R.bench ? "<b>A bench of three</b> each, and a plan for using it." : "No bench: eleven picks each."}</p>`}</div>
      <div class="panel-h"><span class="label">Watching</span><span class="label">${R.is_host ? "your call as host" : "the host's call"}</span></div>
      <div class="room-form">${R.is_host
        ? `<div class="chips" role="radiogroup" aria-label="Watching">
             <button class="chip" role="radio" aria-checked="${R.together}" data-w="1">Together · your clock</button>
             <button class="chip" role="radio" aria-checked="${!R.together}" data-w="0">Each on their own</button></div>`
        : `<p class="note">${R.together ? "<b>Watched together</b> on the host's clock." : "Everyone watches the tournament on their own."}</p>`}</div>
      <div class="panel-h"><span class="label">Ratings</span><span class="label">${R.is_host ? "your call as host" : "the host's call"}</span></div>
      <div class="room-form">${R.is_host
        ? `<div class="chips" role="radiogroup" aria-label="Ratings">
             <button class="chip" role="radio" aria-checked="${!R.memory}" data-m="0">Shown</button>
             <button class="chip" role="radio" aria-checked="${R.memory}" data-m="1">Hidden · Memory</button></div>`
        : `<p class="note">${R.memory ? "<b>Memory mode:</b> nobody sees a rating until the tournament." : "Ratings are shown while you draft."}</p>`}</div>
      <div class="room-form">${R.is_host
        ? `<button class="btn primary" id="startb">Start the draft</button>
           <p class="note">${real ? `${real} empty place${real === 1 ? "" : "s"} will go to real quarter-finalists, one season per club.` : "Every place is taken by a friend."}
           Late arrivals can't join once it starts.</p>`
        : `<p class="note waiting">Waiting for the host to start the draft…</p>`}</div>
    </section>
    <section class="panel">
      <div class="panel-h"><span class="label">How a room plays</span></div>
      <ol class="howto">
        ${R.style === "turns"
          ? `<li><b>Take turns</b> in a snake: first in one round, last in the next. Each turn deals one real squad to whoever is picking.</li>
             <li><b>A player taken is gone for everyone</b>, in every season. You have ${R.timer} seconds a pick, or one is made for you.</li>
             <li>${R.picks_each === 11 ? "Eleven" : "Fourteen"} rounds: at most about ${Math.ceil((R.seats.length * R.picks_each * R.timer) / 60)} minutes with ${R.seats.length} ${R.seats.length === 1 ? "player" : "players"}.</li>`
          : `<li>Everyone is dealt from the <b>same shuffle</b>, so you all see the same squads in the same order.</li>
             <li>Draft at your own pace: one player per squad, two rerolls, just like the solo game.</li>`}
        ${R.bench ? "<li><b>A bench of three:</b> after your eleven, three more picks. Then everyone plans their changes and says they're ready; the tournament opens when all of you are.</li>" : ""}
        ${R.together ? "<li><b>Watch it together:</b> once the tournament opens, the host kicks off and everyone sees the same matches at the same moment, a round at a time. Only the host can skip ahead.</li>" : ""}
        ${R.memory ? "<li><b>Memory mode:</b> no ratings until the tournament. Pick on what you remember.</li>" : ""}
        <li>When the last eleven is in: ${esc(R.stages.join(" → "))}. ${R.size === 2 ? "Winner takes all." : R.size === 36 ? "Eight league matches each against eight different sides, then two-legged ties; the final is one night on neutral ground." : "Ties are two legs; the final is one night on neutral ground."}</li>
      </ol>
      <div class="room-form"><button class="btn ghost small" id="leaveb">Leave room</button></div>
    </section></div>`;
  loadMeta().then((m) => {
    const el = $("forms");
    if (!el) return;
    el.innerHTML = m.formations.map((f) => `<button class="chip" role="radio" aria-checked="${f.code === you.code}" data-c="${f.code}">${esc(f.label)}</button>`).join("");
    el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { store.set("formation", b.dataset.c); act("formation", { formation: b.dataset.c }); });
    const by = Object.fromEntries(m.formations.map((f) => [f.code, f]));
    const show = (f) => showShape("lobbyshape", f);
    previewOnHover(el, by, "data-c", show, () => you.code);
    show(by[you.code]);
  }).catch(() => {});
  $("view").querySelectorAll("[data-m]").forEach((b) => b.onclick = () => act("memory", { memory: b.dataset.m === "1" }));
  $("view").querySelectorAll("[data-b]").forEach((b) => b.onclick = () => act("bench", { bench: b.dataset.b === "1" }));
  $("view").querySelectorAll("[data-w]").forEach((b) => b.onclick = () => act("together", { together: b.dataset.w === "1" }));
  $("view").querySelectorAll("[data-style]").forEach((b) => b.onclick = () => act("style", { style: b.dataset.style, timer: R.timer }));
  $("view").querySelectorAll("[data-timer]").forEach((b) => b.onclick = () => act("style", { style: R.style, timer: +b.dataset.timer }));
  if ($("startb")) $("startb").onclick = () => act("start");
  $("leaveb").onclick = async () => {
    if (!confirm("Leave this room?")) return;
    try { await api(`/api/rooms/${CODE}/leave`, { method: "POST" }); location.href = "/friends"; }
    catch (e) { toast(e.message); }
  };
}

// ------------------------------------------------------------------ the draft

function renderDrafting() {
  const you = R.seats.find((s) => s.you);
  const waitingOn = R.seats.filter((s) => !s.complete);
  if (!you || you.complete) {
    shown = null;
    const names = waitingOn.map((s) => esc(s.username)).join(", ");
    $("view").innerHTML = `<div class="friends-grid">
      <section class="panel gate"><div><h2>${you ? "Your eleven is in" : "The draft is under way"}</h2>
        <p>Waiting for ${names || "the last pick"}. The tournament opens the moment the last eleven is full.</p>
        ${R.is_host ? `<p class="note">Someone wandered off? You can finish every unfinished eleven with the best
          player each of their remaining squads offers.</p>` : ""}</div>
        <div class="gate-cta">${R.is_host ? `<button class="btn ghost" id="finishb">Finish their drafts</button>` : ""}</div></section>
      ${R.draft ? `<aside class="panel"><div class="panel-h"><span class="label">Your XI</span><span class="label">${esc(R.draft.formation.label)}</span></div>
        <div class="pitch" id="pitch"></div></aside>` : ""}</div>`;
    if (R.draft) renderPitch($("pitch"), R.draft.formation.slots, R.draft.xi, null);
    if ($("finishb")) $("finishb").onclick = () => { if (confirm(`Finish the drafts of ${waitingOn.map((s) => s.username).join(", ")}?`)) act("finish"); };
    return;
  }
  const d = R.draft;
  if (d.state === shown && $("deal")) return;        // a poll; nothing of yours changed
  const fresh = shown !== null || !$("deal");
  if (!$("deal")) {
    $("view").innerHTML = `<div class="draft-top"><h2 class="h2 tight" id="formname"></h2>
        <div class="progress"><span class="label">Pick <b id="pickno">1</b> of ${d.total}${R.memory ? ` · <span class="memtag">Memory</span>` : ""}</span>
        <div class="bar"><i id="bar" style="width:0"></i></div></div>
        <div class="linechips" id="lines" aria-label="Places filled in each line"></div></div>
      <div class="draft-grid">
        <section class="panel deal" id="deal" aria-live="polite"></section>
        <aside class="panel"><div class="panel-h"><span class="label">Your XI</span><span class="label" id="xisub"></span></div>
          <div class="pitch" id="pitch"></div><div class="bench-row" id="bench" hidden></div><div class="xi-foot" id="xifoot"></div></aside></div>`;
  }
  shown = d.state;
  const forBench = d.picks.length >= 11;
  $("formname").textContent = d.formation.label;
  $("pickno").textContent = d.picks.length + 1;
  $("bar").style.width = `${(d.picks.length / d.total) * 100}%`;
  lineChips($("lines"), d.formation, d.xi);
  const expect = movesIn(d.state);
  renderDeal($("deal"), d.deal, {
    heading: forBench ? `For your bench · ${d.picks.length - 10} of ${d.bench_size}` : "Dealt to the room",
    takeLabel: forBench ? "Bench" : undefined, rerollsLeft: d.rerolls_left, fresh,
    onTake: (i) => act("pick", { index: i, expect }), onReroll: () => act("reroll", { expect }),
  });
  renderPitch($("pitch"), d.formation.slots, d.xi, d.picks.length && !forBench ? d.picks[d.picks.length - 1].id : null);
  renderBench($("bench"), d.bench, d.bench_size);
  pitchPeek($("pitch"), d);
  $("xisub").textContent = d.bench_size ? `${d.xi.length} / 11 · bench ${d.bench.length} / ${d.bench_size}` : `${d.picks.length} / 11`;
  xiFoot($("xifoot"), { ...d, picks: d.picks.slice(0, 11) });
}

// ------------------------------------------------------------------ the plan (C42)

/* A bench room's last step: each seat plans its changes and says it is ready, and the
   tournament opens when everyone is. Choosing here changes nothing on the server until
   Ready, since sending a plan is what says you are ready; after that every change is
   sent at once, until the room completes. */
let localPlan = null;
const planning = () => R.status === "drafting" && R.bench && R.draft && R.draft.complete;

function renderPlanning() {
  shown = null; shownTurn = null;
  document.title = TITLE;
  const d = R.draft, ready = d.ready;
  if (ready) localPlan = null;
  const waiting = R.seats.filter((s) => !s.complete || !s.ready).map((s) => s.username);
  if (!$("plan")) {
    $("view").innerHTML = `<div class="draft-grid">
      <section class="panel deal" id="plan"></section>
      <aside class="panel"><div class="panel-h"><span class="label">Your XI</span><span class="label">${esc(d.formation.label)}</span></div>
        <div class="pitch" id="pitch"></div><div class="bench-row" id="bench" hidden></div></aside></div>`;
  }
  const finish = R.is_host && waiting.length ? `<button class="btn ghost" id="finishb">Finish for everyone</button>` : "";
  planPanel($("plan"), d, !ready && localPlan ? localPlan : d.plan, {
    tag: ready ? "ready" : localPlan || d.plan_chosen ? "your plan" : "automatic plan",
    onChange: (p) => { if (ready) act("plan", { changes: p }); else { localPlan = p; renderPlanning(); } },
    // A live room (C60): make the changes yourself while the room watches; a pause stops everyone.
    mode: R.live ? { manual: d.manual, onMode: (manual) => act("manual", { manual }) } : null,
    foot: ready
      ? `<p class="note waiting">Ready. ${waiting.length ? `Waiting for ${esc(waiting.join(", "))}.` : "Opening the tournament…"}
          You can change your plan until everyone is.</p>${finish}`
      : `<button class="btn primary" id="readyb">Ready</button>${finish}
         <p class="label">The tournament opens when everyone is ready. ${AUTO_NOTE}</p>`,
  });
  renderPitch($("pitch"), d.formation.slots, d.xi, null);
  renderBench($("bench"), d.bench, d.bench_size);
  // The team sheet (C44) goes to the server at once; a plan not yet sent follows its men.
  if (!$("sheethint")) $("bench").insertAdjacentHTML("afterend", `<p class="sheet-hint" id="sheethint"></p>`);
  const sendSheet = async (body) => {
    const before = R.draft;
    await act("sheet", body);
    if (localPlan && R.draft && R.draft !== before) { localPlan = carryPlan(localPlan, before, R.draft); renderPlanning(); }
  };
  sheetEditor($("pitch"), $("bench"), d, {
    hint: $("sheethint"), onMove: (man, to) => sendSheet({ man, to }), reset: d.sheet_chosen ? () => sendSheet({}) : null,
  });
  if ($("readyb")) $("readyb").onclick = () => act("plan", { changes: localPlan || (d.plan_chosen ? d.plan : null) });
  if ($("finishb")) $("finishb").onclick = () => {
    if (confirm(`Finish for ${waiting.join(", ")}? Unmade picks take the best player each squad offers, and anyone not ready gets the automatic plan.`)) act("finish");
  };
}

// ------------------------------------------------------------------ taking turns (C29)

let ticker = null;
let shownTurn = null;     // the pick number the deal on screen belongs to

function renderFailed() {
  shownTurn = null;
  $("view").innerHTML = `<section class="panel gate"><div><h2>This draft couldn't finish</h2>
    <p>${esc(R.failure_reason || "Something went wrong.")}</p></div>
    <div class="gate-cta"><a class="btn primary" href="/friends">Start another room</a></div></section>`;
}

function renderTurns() {
  const T = R.turns, d = R.draft, mine = T.turn && T.turn.you;
  if (!$("tdeal")) {
    $("view").innerHTML = `<div class="turnbar" id="turnbar"></div>
      <div class="draft-top">${d ? `<h2 class="h2 tight" id="formname"></h2>` : ""}
        <div class="progress"><span class="label">Round <b id="roundno">1</b> of ${T.rounds}${R.memory ? ` · <span class="memtag">Memory</span>` : ""}</span>
          <div class="bar"><i id="bar" style="width:0"></i></div></div>
        ${d ? `<div class="linechips" id="lines" aria-label="Places filled in each line"></div>` : ""}</div>
      <div class="draft-grid">
        <section class="panel deal" id="tdeal" aria-live="polite"></section>
        <aside class="cup-stack">
          ${d ? `<section class="panel"><div class="panel-h"><span class="label">Your XI</span><span class="label" id="xisub"></span></div>
            <div class="pitch" id="pitch"></div><div class="bench-row" id="bench" hidden></div></section>` : ""}
          <section class="panel"><div class="panel-h"><span class="label">Latest picks</span><span class="label" id="pickcount"></span></div>
            <ol class="feed-list" id="recent"></ol></section>
        </aside></div>`;
  }
  // The banner and clock change every turn; the deal only when the turn does.
  $("turnbar").innerHTML = T.turn ? `<div class="turnbar-in ${mine ? "mine" : ""}" style="${teamStyle(T.turn)}">
      ${sideCrest({ human: true, name: T.turn.username, ...T.turn }, 36)}
      <div class="tb-who"><b>${mine ? "Your pick" : `${esc(T.turn.username)} is picking`}</b>
        <small>Pick ${T.expect + 1} of ${T.total}</small></div>
      <div class="tb-clock"><span id="secs">–</span><div class="tb-gauge"><i id="gauge"></i></div></div></div>` : "";
  $("roundno").textContent = T.round;
  $("bar").style.width = `${(T.expect / T.total) * 100}%`;
  document.title = mine ? `● Your pick · ${TITLE}` : TITLE;
  if (d) {
    $("formname").textContent = d.formation.label;
    lineChips($("lines"), d.formation, d.xi);
    renderPitch($("pitch"), d.formation.slots, d.xi, d.picks.length && d.picks.length <= 11 ? d.picks[d.picks.length - 1].id : null);
    renderBench($("bench"), d.bench, d.bench_size);
    pitchPeek($("pitch"), d);
    $("xisub").textContent = d.bench_size ? `${d.xi.length} / 11 · bench ${d.bench.length} / ${d.bench_size}` : `${d.picks.length} / 11`;
  }
  if (T.deal && shownTurn !== T.expect) {
    const fresh = shownTurn !== null;
    shownTurn = T.expect;
    const forBench = mine && d && d.picks.length >= 11;
    renderDeal($("tdeal"), T.deal, {
      headingHtml: forBench ? "Dealt to you · for your bench" : mine ? "Dealt to you" : `Dealt to ${esc(T.turn.username)}`,
      takeLabel: forBench ? "Bench" : undefined, fresh, readOnly: !mine,
      onTake: (i) => act("pick", { index: i, expect: T.expect }),
    });
    if (mine && fresh && navigator.vibrate) navigator.vibrate(120);
  }
  $("pickcount").textContent = `${T.expect} made`;
  $("recent").innerHTML = T.recent.length ? T.recent.map((r) => `<li style="${teamStyle(r)}">
      <span class="dot" aria-hidden="true"></span><b>${esc(r.username)}</b>
      <span class="pick-name">${esc(r.card.name)}</span>${positionsHtml(r.card)}
      <small>${esc(r.card.short)} ${esc(r.card.season.slice(2))}${r.card.rating == null ? "" : ` · ${r.card.rating}`}</small></li>`).join("")
    : `<li class="empty">No picks yet.</li>`;
  startTicker();
}

/* The countdown, redrawn four times a second from the synced clock, separately from
   the polls (the cricket site's A91: the display clock is not the poll clock). */
function startTicker() {
  clearInterval(ticker);
  const tick = () => {
    const T = R && R.turns;
    if (!T || !T.turn || !$("secs")) return clearInterval(ticker);
    const left = Math.max(0, T.timer - (serverNow() - T.turn_started_at));
    $("secs").textContent = Math.ceil(left);
    $("gauge").style.width = `${(left / T.timer) * 100}%`;
    $("turnbar").classList.toggle("urgent", left <= 5);
  };
  tick();
  ticker = setInterval(tick, 250);
}

// ------------------------------------------------------------------ boot

document.addEventListener("visibilitychange", () => {
  if (document.hidden) clearTimeout(timer);
  else if (R) poll();
});
window.addEventListener("online", () => { if (R) poll(); });

(function boot() {
  if (!/^[A-Z0-9]{6}$/.test(CODE)) return gone("That isn't a room code. A code is six letters and numbers.");
  onAuth(() => { if (R) { R = null; shown = null; poll(); } });   // seated and host depend on who you are
  poll();
})();
