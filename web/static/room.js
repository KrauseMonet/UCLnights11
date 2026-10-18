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
// An auction's clock (C70) is the room's business every second: an open lot can close
// eight seconds after a raise, and a sealed round closes the moment the last bid is in.
const auctioning = () => R && R.auction && R.status === "drafting" && !R.auction.complete;
const AUCTION_POLL_MS = { open: 700, sealed: 1000 };
const STYLE_NAME = { turns: "take turns", own: "own pace", sealed: "sealed-bid auction", open: "open auction" };
const CLOCKS = { turns: [[15, 30, 45], "a pick", 30], open: [[15, 30, 45], "to nominate", 30], sealed: [[30, 45, 60], "a round", 45] };
const OPEN_SIZES = [2, 4, 8];   // game.open_auction.ROOM_SIZES

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

function schedule(ms = auctioning() ? AUCTION_POLL_MS[R.style] : takingTurns() ? TURN_POLL_MS : POLL_MS) {
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
    sampleClock(t0, Date.now(), room.unchanged ? room.server_now
      : room.turns ? room.turns.server_now : room.auction && room.auction.server_now);
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
    <div><div class="kicker">${esc(R.format)} · ${esc(STATUS[R.status] || R.status)}${R.style === "own" ? " · own pace" : ` · ${STYLE_NAME[R.style]}, ${R.timer}s`}${R.bench ? " · bench" : ""}${R.together ? " · watch together" : ""}${R.memory ? " · Memory" : ""}</div>
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
  else if (R.auction) renderAuction();
  else if (R.style === "turns") renderTurns();
  else renderDrafting();
}

function renderStrip() {
  const kick = R.is_host && R.status === "lobby";
  $("strip").innerHTML = R.seats.map((s, k) => `
    <div class="seatcard ${s.you ? "me" : ""} ${s.complete && s.ready ? "done" : ""} ${R.turns && R.turns.turn && R.turns.turn.id === s.id ? "on" : ""}" style="${teamStyle(s)}">
      ${sideCrest({ human: true, name: s.username, ...s }, 36)}
      <div class="who"><b>${esc(s.username)}${s.host ? ' <span class="host" title="Host">host</span>' : ""}</b>
        <small>${esc(s.formation)}${R.status === "lobby" ? "" : R.auction && !s.complete ? ` · €${R.auction.seats[k].money}m · ${R.auction.seats[k].places} to buy${R.auction.has_bid && R.auction.has_bid[k] ? " · bid in" : ""}` : !s.complete ? ` · ${s.picks}/${R.picks_each}` : !R.bench ? " · eleven in" : s.ready ? " · ready" : " · planning"}</small>
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
             <button class="chip" role="radio" aria-checked="${R.style === "own"}" data-style="own">Own pace</button>
             <button class="chip" role="radio" aria-checked="${R.style === "sealed"}" data-style="sealed">Auction · sealed bids</button>
             <button class="chip ${OPEN_SIZES.includes(R.size) ? "" : "off"}" role="radio" aria-checked="${R.style === "open"}" data-style="open">Auction · open${OPEN_SIZES.includes(R.size) ? "" : " (8 at most)"}</button></div>
           ${CLOCKS[R.style] ? `<div class="chips" role="radiogroup" aria-label="Clock">${CLOCKS[R.style][0].map((t) =>
             `<button class="chip" role="radio" aria-checked="${R.timer === t}" data-timer="${t}">${t}s ${CLOCKS[R.style][1]}</button>`).join("")}</div>` : ""}`
        : `<p class="note">${{ turns: `<b>Taking turns</b>, ${R.timer} seconds a pick.`, own: "<b>Own pace:</b> everyone drafts at once.",
             sealed: `<b>A sealed-bid auction</b>, ${R.timer} seconds a round.`, open: `<b>An open auction</b>, ${R.timer} seconds to nominate.` }[R.style]}</p>`}</div>
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
        ${R.style === "sealed"
          ? `<li><b>Everyone has €200m.</b> Each round a market of real squads is dealt to the whole room, and everyone bids in secret on up to five men.</li>
             <li>A round closes when everyone has bid, or after ${R.timer} seconds. <b>Each of you wins at most one man a round</b>, the highest bids first, and pays €1m more than the next bid on him, never more than you bid.</li>
             <li>You always keep €1m for every place you still have to fill. Send nothing and a €1m bid is made for you.</li>`
          : R.style === "open"
          ? `<li><b>Everyone has €200m.</b> You take turns to nominate: you're dealt a real squad, put one man up, and open the bidding at €1m yourself.</li>
             <li>Anyone who can play him raises. A lot closes 12 seconds after it goes up or 8 after the last bid. The winner pays his bid.</li>
             <li>You always keep €1m for every place you still have to fill. ${R.timer} seconds to nominate, or a man is put up for you.</li>`
          : R.style === "turns"
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
  $("view").querySelectorAll("[data-style]").forEach((b) => b.onclick = () => {
    const s = b.dataset.style;
    if (s === "open" && !OPEN_SIZES.includes(R.size)) return toast("An open auction is for rooms of up to 8: a bigger room would take well over an hour. Sealed bids work for any size.");
    const c = CLOCKS[s];
    // Own pace keeps a pick clock's choices, so a sealed round's 60 s goes back to 30.
    const choices = c ? c[0] : CLOCKS.turns[0];
    act("style", { style: s, timer: choices.includes(R.timer) ? R.timer : c ? c[2] : 30 });
  });
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

// ------------------------------------------------------------------ auctions (C70)

let shownAuction = null;   // what the auction panel on screen belongs to: a sealed round, or an open lot
let heardSale = null;      // the latest sale this page has rung the gavel for (C72)
let myBids = new Map();    // a sealed round's bids as written here, lot -> amount, until they are sent
const eur = (x) => `€${x}m`;
const seatOf = (k) => R.seats[k] || { username: "?" };

function renderAuction() {
  const A = R.auction, d = R.draft;
  const key = A.kind === "sealed" ? `s${A.round}` : `o${A.lots_done}:${A.lot ? A.lot.number : "-"}`;
  if (!$("amain")) {
    shownAuction = null;
    $("view").innerHTML = `<div class="turnbar" id="abar"></div>
      <div class="draft-top">${d ? `<h2 class="h2 tight" id="formname"></h2>` : ""}
        <div class="progress"><span class="label" id="aprog"></span><div class="bar"><i id="bar" style="width:0"></i></div></div>
        ${d ? `<div class="linechips" id="lines" aria-label="Places filled in each line"></div>` : ""}</div>
      <div class="draft-grid auc-grid">
        <section class="panel deal auc-main" id="amain" aria-live="polite"></section>
        <aside class="cup-stack">
          ${A.kind === "sealed" && d ? `<section class="panel" id="amine"></section>` : ""}
          ${d ? `<section class="panel"><div class="panel-h"><span class="label">Your squad</span><span class="label" id="xisub"></span></div>
            <div class="pitch" id="pitch"></div><div class="bench-row" id="bench" hidden></div></section>` : ""}
          <section class="panel"><div class="panel-h"><span class="label">Sales</span><span class="label" id="salecount"></span></div>
            <ol class="feed-list auc-sales" id="asales"></ol></section>
          ${R.is_host ? `<section class="panel"><div class="room-form"><button class="btn ghost small" id="afinish">Finish the auction</button>
            <p class="note">Someone wandered off? Every place left is filled with a random man each seat can take, at ${eur(A.min_bid)}${A.kind === "open" ? ", and the man up now goes to whoever leads" : ", after this round closes with the bids sent"}.</p></div></section>` : ""}
        </aside></div>`;
    if ($("afinish")) $("afinish").onclick = () => {
      if (confirm(`Finish the auction for everyone? Every place left is filled with a random man at ${eur(R.auction.min_bid)}.`)) act("finish");
    };
  }
  const bought = A.seats.reduce((n, s) => n + (R.picks_each - s.places), 0), all = R.picks_each * A.seats.length;
  $("aprog").innerHTML = A.kind === "sealed" ? `Round <b>${A.round}</b> · ${bought} of ${all} bought${R.memory ? ` · <span class="memtag">Memory</span>` : ""}`
    : `Lot <b>${A.lot ? A.lot.number : A.lots_done + 1}</b> · ${bought} of ${all} bought${R.memory ? ` · <span class="memtag">Memory</span>` : ""}`;
  $("bar").style.width = `${(bought / all) * 100}%`;
  if (d) {
    $("formname").textContent = d.formation.label;
    lineChips($("lines"), d.formation, d.xi);
    renderPitch($("pitch"), d.formation.slots, d.xi, null);
    renderBench($("bench"), d.bench, d.bench_size);
    $("xisub").textContent = d.bench_size ? `${d.xi.length} / 11 · bench ${d.bench.length} / ${d.bench_size}` : `${d.picks.length} / 11`;
  }
  const fresh = shownAuction !== key;
  shownAuction = key;
  if (A.kind === "sealed") renderSealed(A, d, fresh); else renderOpen(A, d, fresh);
  renderSales(A);
  // A sale that happened while you watched rings the gavel; one already made when the page
  // opened doesn't.
  const latest = A.sales.length ? `${A.sales[0].seat}:${A.sales[0].card.id}:${A.sales[0].price}` : "";
  if (heardSale !== null && latest && latest !== heardSale) gavel();
  heardSale = latest;
  startAuctionTicker();
}

/* "Sold": two knocks of a gavel, synthesized as the match sounds are (C60), silent when the
   speaker is off there (the same setting). A browser only lets a page sound after a tap. */
let ACTX = null;
function gavel() {
  if (store.get("sound") === "off") return;
  try {
    ACTX ||= new (window.AudioContext || window.webkitAudioContext)();
    if (ACTX.state === "suspended") ACTX.resume();
    const t0 = ACTX.currentTime + 0.02;
    for (const at of [0, 0.18]) {
      const o = ACTX.createOscillator(), g = ACTX.createGain(), a = t0 + at;
      o.type = "triangle";
      o.frequency.setValueAtTime(320, a);
      o.frequency.exponentialRampToValueAtTime(90, a + 0.09);
      g.gain.setValueAtTime(0.0001, a);
      g.gain.exponentialRampToValueAtTime(0.35, a + 0.005);
      g.gain.exponentialRampToValueAtTime(0.0001, a + 0.12);
      o.connect(g).connect(ACTX.destination);
      o.start(a); o.stop(a + 0.15);
    }
  } catch { /* no sound is no failure */ }
}

/* What the seat bar says: whose move it is and the clock, in the room's own words. */
function auctionBar(A, html, mine) {
  $("abar").innerHTML = `<div class="turnbar-in ${mine ? "mine" : ""}">${html}
    <div class="tb-clock"><span id="asecs">–</span><div class="tb-gauge"><i id="agauge"></i></div></div></div>`;
}

function renderSales(A) {
  $("salecount").textContent = A.sales.length ? `latest ${A.sales.length}` : "";
  $("asales").innerHTML = A.sales.length ? A.sales.map((s) => {
    const who = seatOf(s.seat);
    const others = s.others.length ? ` · beat ${s.others.map((o) => `${esc(seatOf(o.seat).username)} ${eur(o.amount)}`).join(", ")}` : "";
    return `<li style="${teamStyle(A.seats[s.seat])}"><span class="dot" aria-hidden="true"></span><b>${esc(who.username)}</b>
      <span class="pick-name">${esc(s.card.name)}</span><span class="auc-price">${eur(s.price)}</span>
      <small>${esc(s.card.short)} ${esc(s.card.season.slice(2))}${s.card.rating == null ? "" : ` · ${s.card.rating}`}${others}</small></li>`;
  }).join("") : `<li class="empty">Nothing sold yet.</li>`;
}

// -- sealed rounds

function renderSealed(A, d, fresh) {
  const me = A.you, seat = me == null ? null : A.seats[me];
  const buying = seat && seat.places > 0;
  const sent = A.bid != null;
  auctionBar(A, `<div class="tb-who"><b>${!buying ? "Watching the round" : sent ? "Your bids are in" : "Your bids, in secret"}</b>
    <small>Round ${A.round} · ${A.has_bid.filter(Boolean).length} of ${A.seats.filter((s) => s.places > 0).length} have bid${buying ? ` · you have ${eur(seat.money)}, up to ${eur(A.max_bid)} a man` : ""}</small></div>`, buying && !sent);
  if (fresh) {
    myBids = new Map(A.bid || []);
    let k = 0;
    $("amain").style.cssText = "";
    $("amain").innerHTML = `<div class="panel-h"><span class="label">Round ${A.round} · the market</span>
        <span class="label"><b>${A.market.reduce((n, cs) => n + cs.cards.filter((c) => c.takeable).length, 0)}</b> you can buy</span></div>
      ${A.market.map((cs) => `<details class="mkt" ${k++ < 3 ? "open" : ""} style="${teamStyle(cs)}">
        <summary class="mkt-h">${crest(cs.crest, 36, cs.name)}<span><b>${esc(cs.name)}</b><small>${esc(cs.season)}</small></span>
          <span class="label">${cs.cards.filter((c) => c.takeable).length} of ${cs.cards.length}</span></summary>
        ${cs.cards.map((c) => `<div class="row ${c.takeable ? "" : "off"}">${positionsHtml(c)}
          <div class="who"><b>${esc(c.name)}</b><small>${altPositions(c)}${esc(c.nation || "")}</small></div>
          ${c.rating == null ? "" : rate(c.rating)}
          ${c.takeable && buying ? `<button class="take" data-lot="${c.i}" aria-pressed="false">Bid</button>` : c.takeable ? "" : `<span class="why">${whyHtml(c.reason)}</span>`}
        </div>`).join("")}</details>`).join("")}`;
    $("amain").querySelectorAll("[data-lot]").forEach((b) => b.onclick = () => {
      const lot = +b.dataset.lot;
      if (myBids.has(lot)) myBids.delete(lot);
      else if (myBids.size >= A.max_bids) return toast(`At most ${A.max_bids} bids a round`);
      else myBids.set(lot, A.min_bid);
      drawMyBids(A);
    });
  }
  drawMyBids(A);
}

function lotCard(A, lot) {
  for (const cs of A.market) for (const c of cs.cards) if (c.i === lot) return c;
  return null;
}

/* Your bids for the round: each man you've chosen, an amount for each, and send or pass.
   They are sent as a whole and replace what you sent before, until the round closes. */
function drawMyBids(A) {
  const el = $("amine");
  if (!el) return;
  const me = A.you, seat = me == null ? null : A.seats[me];
  $("amain").querySelectorAll("[data-lot]").forEach((b) => {
    const on = myBids.has(+b.dataset.lot);
    b.setAttribute("aria-pressed", on);
    b.textContent = on ? "✓ Bidding" : "Bid";
  });
  if (!seat || seat.places <= 0) {
    el.innerHTML = `<div class="panel-h"><span class="label">Your bids</span></div><p class="empty">Your squad is full: you're watching the rest buy.</p>`;
    return;
  }
  const keep = [...el.querySelectorAll("input[data-amt]")].map((i) => [+i.dataset.amt, +i.value]);
  keep.forEach(([lot, x]) => { if (myBids.has(lot) && x) myBids.set(lot, x); });
  const sentText = A.bid == null ? "" : A.bid.length ? `Sent: ${A.bid.map(([l, x]) => `${esc((lotCard(A, l) || {}).name || "?")} ${eur(x)}`).join(", ")}` : "You passed this round";
  el.innerHTML = `<div class="panel-h"><span class="label">Your bids</span><span class="label">${myBids.size} of ${A.max_bids}</span></div>
    <div class="auc-bids">${myBids.size ? [...myBids].map(([lot, x]) => {
      const c = lotCard(A, lot) || { name: "?", positions: [] };
      return `<div class="auc-bid"><div class="who"><b>${esc(c.name)}</b><small>${(c.positions || []).map(posChip).join("")} ${esc(c.short || "")} ${esc((c.season || "").slice(2))}</small></div>
        <label class="auc-amt">€<input type="number" inputmode="numeric" min="${A.min_bid}" max="${A.max_bid}" value="${x}" data-amt="${lot}" aria-label="Bid for ${esc(c.name)}, in millions">m</label>
        <button class="kick" data-drop="${lot}" aria-label="Drop ${esc(c.name)}">✕</button></div>`;
    }).join("") : `<p class="empty">Tap <b>Bid</b> on up to ${A.max_bids} men in the market.</p>`}</div>
    <div class="plan-foot"><button class="btn primary" id="sendbids" ${myBids.size ? "" : "disabled"}>${A.bid != null ? "Change my bids" : "Send my bids"}</button>
      <button class="btn ghost" id="passb" ${A.passes_left > 0 ? "" : "disabled"}>Pass (${A.passes_left} left)</button>
      <p class="label">Up to ${eur(A.max_bid)} a man: you keep ${eur(A.min_bid)} for each other place. You win one man a round at most, your highest bid first, and pay ${eur(1)} more than the next bid on him, never more than you bid.${sentText ? `<br><b>${sentText}</b>` : ""}</p></div>`;
  el.querySelectorAll("[data-drop]").forEach((b) => b.onclick = () => { myBids.delete(+b.dataset.drop); drawMyBids(A); });
  el.querySelectorAll("input[data-amt]").forEach((i) => i.onchange = () => myBids.set(+i.dataset.amt, Math.max(A.min_bid, Math.min(A.max_bid, Math.round(+i.value) || A.min_bid))));
  $("sendbids").onclick = () => {
    const bids = [...myBids].map(([lot, x]) => [lot, Math.max(A.min_bid, Math.min(A.max_bid, Math.round(x)))]);
    act("bids", { round: A.round, bids });
  };
  $("passb").onclick = () => act("bids", { round: A.round, bids: [] });
}

// -- open lots

function renderOpen(A, d, fresh) {
  const me = A.you, seat = me == null ? null : A.seats[me];
  const lot = A.lot;
  if (!lot) {
    const nominating = A.nominator === me;
    const who = seatOf(A.nominator);
    auctionBar(A, `${sideCrest({ human: true, name: who.username, ...A.seats[A.nominator] }, 36)}
      <div class="tb-who"><b>${nominating ? "Your turn to put a man up" : `${esc(who.username)} is choosing who goes up`}</b>
        <small>Lot ${A.lots_done + 1} · ${nominating ? "you open the bidding at €1m, so pick someone you'd buy" : "anyone who can play him can bid"}</small></div>`, nominating);
    if (fresh && A.deal) {
      renderDeal($("amain"), A.deal, {
        headingHtml: nominating ? "Dealt to you · put one man up" : `Dealt to ${esc(who.username)}`,
        takeLabel: "Put up", fresh: true, readOnly: !nominating,
        onTake: (i) => act("nominate", { lot: A.lots_done + 1, index: i }),
      });
      if (nominating && navigator.vibrate) navigator.vibrate(120);
    }
    return;
  }
  if (fresh) dropFlight();          // a nomination's "Put up" lifted him off the deal: he's on the block, not your pitch
  const leader = seatOf(lot.leader), c = lot.card;
  const leading = lot.leader === me;
  auctionBar(A, `${crest(c.crest, 36, c.club)}<div class="tb-who"><b>${esc(c.name)} · ${eur(lot.price)}</b>
    <small>Lot ${lot.number} · ${leading ? "you lead" : `${esc(leader.username)} leads`} · <span id="agoing"></span></small></div>`, !leading && !lot.why_not);
  if (fresh) {
    $("amain").style.cssText = teamStyle({ team: "#7cc4ff", deep: "#10233f", ink: "#c4e5ff", ...A.seats[lot.nominator] });
    $("amain").innerHTML = `<div class="panel-h"><span class="label">Lot ${lot.number} · put up by ${esc(seatOf(lot.nominator).username)}</span><span class="label" id="lotstate"></span></div>
      <div class="band auc-lot">${crest(c.crest, 104, c.club)}
        <div class="deal-year">${esc(c.season)}</div><div class="deal-club">${esc(c.club)}</div>
        <div class="auc-man"><b>${esc(c.name)}</b> ${positionsHtml(c)} ${c.rating == null ? "" : rate(c.rating)}</div></div>
      <div class="auc-live"><div class="auc-now"><span class="label">Price</span><b id="lotprice"></b><small id="lotleader"></small></div>
        <div class="auc-raise" id="raises"></div>
        <form class="auc-own" id="ownbid"><label>€<input type="number" inputmode="numeric" id="ownamt" aria-label="Your bid, in millions">m</label>
          <button class="btn ghost small" type="submit">Bid</button></form>
        <p class="label" id="lotwhy"></p></div>
      <ol class="feed-list auc-hist" id="lothist"></ol>`;
    $("ownbid").onsubmit = (e) => { e.preventDefault(); const x = Math.round(+$("ownamt").value); if (x) act("bid", { lot: R.auction.lot.number, amount: x }); };
  }
  $("lotprice").textContent = eur(lot.price);
  $("lotleader").textContent = leading ? "You lead" : `${leader.username} leads`;
  const why = lot.why_not;
  const top = A.max_bid == null ? 0 : A.max_bid;
  $("raises").innerHTML = [1, 5, 10].map((n) => {
    const x = lot.price + n;
    return `<button class="btn ${n === 1 ? "primary" : "ghost"}" data-raise="${x}" ${why || x > top ? "disabled" : ""}>${eur(x)}</button>`;
  }).join("");
  $("raises").querySelectorAll("[data-raise]").forEach((b) => b.onclick = () => act("bid", { lot: lot.number, amount: +b.dataset.raise }));
  const own = $("ownamt");
  own.min = lot.price + lot.min_raise; own.max = top;
  if (!own.value || +own.value <= lot.price) own.placeholder = String(lot.price + lot.min_raise);
  $("ownbid").querySelector("button").disabled = !!why;
  $("lotwhy").textContent = why ? (why === "you lead the bidding" ? "You lead: wait to be outbid." : `You can't bid: ${why}.`) : `You can bid up to ${eur(top)}.`;
  $("lothist").innerHTML = lot.bids.length ? [...lot.bids].reverse().map((b) => `<li style="${teamStyle(A.seats[b.seat])}"><span class="dot"></span><b>${esc(seatOf(b.seat).username)}</b> <span class="auc-price">${eur(b.amount)}</span></li>`).join("")
    : `<li class="empty">${esc(seatOf(lot.nominator).username)} opened at ${eur(lot.price)}.</li>`;
}

/* The auction's clock, from the synced server clock four times a second: a sealed round's,
   an open lot's (with its "going once, going twice"), or a nomination's. */
let aticker = null;
function startAuctionTicker() {
  clearInterval(aticker);
  const tick = () => {
    const A = R && R.auction;
    if (!A || !$("asecs") || A.complete) return clearInterval(aticker);
    let end, span;
    if (A.kind === "sealed") { end = A.closes_at; span = A.timer; }
    else if (A.lot) { end = A.lot.ends_at; span = 12; }
    else { end = A.nominate_by; span = A.timer; }
    const left = Math.max(0, end - serverNow());
    $("asecs").textContent = Math.ceil(left);
    $("agauge").style.width = `${Math.min(100, (left / span) * 100)}%`;
    $("abar").firstElementChild && $("abar").firstElementChild.classList.toggle("urgent", left <= 5);
    if (A.lot && $("agoing")) {
      const words = left > 5 ? "bidding open" : left > 2.5 ? "going once…" : left > 0 ? "going twice…" : "sold?";
      $("agoing").textContent = words;
      if ($("lotstate")) $("lotstate").textContent = words;
    }
  };
  tick();
  aticker = setInterval(tick, 250);
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
