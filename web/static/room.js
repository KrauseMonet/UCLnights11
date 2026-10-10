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
const MAX_BACKOFF_MS = 20000;
const STATUS = { lobby: "Lobby", drafting: "Drafting", complete: "Finished" };
let R = null;              // the room as last applied
let shown = null;          // the draft state the deal on screen belongs to
let busy = false;
let timer = null;
let inflight = null;       // the one poll in flight: a timer, a tab waking and a failed move can all ask at once
let failures = 0;
let dead = false;
let wantsJoin = new URLSearchParams(location.search).has("join");

const movesIn = (state) => { const p = state.split("-"); return p.length === 3 && p[2] ? p[2].split(".").length : 0; };
const inviteUrl = () => `${location.origin}/room?join=1#${CODE}`;

function apply(room) {
  if (R && room.version < R.version) return;
  const same = R && room.version === R.version && room.seated === R.seated && room.is_host === R.is_host;
  R = room;
  if (R.status === "complete") { location.replace(`/cup?room=${R.code}`); return; }
  if (!same) render();                               // nothing new: leave the screen alone
  maybeJoin();
}

function schedule(ms) {
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
  try { room = await api(`/api/rooms/${CODE}`); }
  catch (e) {
    if (e.status === 404) return gone(e.message);
    failures += 1;
    connection(e.message);
    return schedule(Math.min(POLL_MS * 2 ** failures, MAX_BACKOFF_MS));
  }
  if (failures) { failures = 0; connection(null); }
  apply(room);
  schedule(POLL_MS);
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
    // twice is refused by its `expect`, so asking again can't take a second player.
    toast(e.status === 0 ? "Connection dropped. Checking whether that went through…" : e.message);
    poll();
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
    <div><div class="kicker">${esc(R.format)} · ${esc(STATUS[R.status])}${R.memory ? " · Memory" : ""}</div>
      <h1 class="room-code" aria-label="Room code ${esc(R.code)}">${esc(R.code)}</h1>
      <p class="sub">${R.seats.length} of ${R.size} players${R.fillers ? ` · ${R.fillers} place${R.fillers === 1 ? "" : "s"} for real sides` : ""}${you ? "" : " · watching"}</p></div>
    <div class="room-acts">${R.status === "lobby" ? `<button class="btn ghost small" id="invite">Copy invite link</button>` : ""}
      <a class="btn ghost small" href="/friends">All rooms</a></div>`;
  const inv = $("invite");
  if (inv) inv.onclick = () => copyText(inviteUrl(), "Invite link copied");
  renderStrip();
  if (R.status === "lobby") renderLobby();
  else renderDrafting();
}

function renderStrip() {
  const kick = R.is_host && R.status === "lobby";
  $("strip").innerHTML = R.seats.map((s) => `
    <div class="seatcard ${s.you ? "me" : ""} ${s.complete ? "done" : ""}" style="${teamStyle(s)}">
      ${sideCrest({ human: true, name: s.username, ...s }, 36)}
      <div class="who"><b>${esc(s.username)}${s.host ? ' <span class="host" title="Host">host</span>' : ""}</b>
        <small>${esc(s.formation)}${R.status === "lobby" ? "" : s.complete ? " · eleven in" : ` · ${s.picks}/11`}</small>
        ${R.status === "drafting" ? `<div class="mini"><i style="width:${(s.picks / 11) * 100}%"></i></div>` : ""}</div>
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
      <div class="room-form"><div class="chips" id="forms" role="radiogroup" aria-label="Formation"></div></div>
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
        <li>Everyone is dealt from the <b>same shuffle</b>, so you all see the same squads in the same order.</li>
        <li>Draft at your own pace: one player per squad, two rerolls, just like the solo game.</li>
        ${R.memory ? "<li><b>Memory mode:</b> no ratings until the tournament. Pick on what you remember.</li>" : ""}
        <li>When the last eleven is in: ${esc(R.stages.join(" → "))}. ${R.size === 2 ? "Winner takes all." : "Ties are two legs; the final is one night on neutral ground."}</li>
      </ol>
      <div class="room-form"><button class="btn ghost small" id="leaveb">Leave room</button></div>
    </section></div>`;
  loadMeta().then((m) => {
    const el = $("forms");
    if (!el) return;
    el.innerHTML = m.formations.map((f) => `<button class="chip" role="radio" aria-checked="${f.code === you.code}" data-c="${f.code}">${esc(f.label)}</button>`).join("");
    el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { store.set("formation", b.dataset.c); act("formation", { formation: b.dataset.c }); });
  }).catch(() => {});
  $("view").querySelectorAll("[data-m]").forEach((b) => b.onclick = () => act("memory", { memory: b.dataset.m === "1" }));
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
    if (R.draft) renderPitch($("pitch"), R.draft.formation.code, R.draft.picks, null);
    if ($("finishb")) $("finishb").onclick = () => { if (confirm(`Finish the drafts of ${waitingOn.map((s) => s.username).join(", ")}?`)) act("finish"); };
    return;
  }
  const d = R.draft;
  if (d.state === shown && $("deal")) return;        // a poll; nothing of yours changed
  const fresh = shown !== null || !$("deal");
  if (!$("deal")) {
    $("view").innerHTML = `<div class="draft-top"><h2 class="h2 tight" id="formname"></h2>
        <div class="progress"><span class="label">Pick <b id="pickno" style="color:var(--gold)">1</b> of 11${R.memory ? ` · <span class="memtag">Memory</span>` : ""}</span>
        <div class="bar"><i id="bar" style="width:0"></i></div></div>
        <div class="linechips" id="lines" aria-label="Places filled in each line"></div></div>
      <div class="draft-grid">
        <section class="panel deal" id="deal" aria-live="polite"></section>
        <aside class="panel"><div class="panel-h"><span class="label">Your XI</span><span class="label" id="xisub"></span></div>
          <div class="pitch" id="pitch"></div><div class="xi-foot" id="xifoot"></div></aside></div>`;
  }
  shown = d.state;
  $("formname").textContent = d.formation.label;
  $("pickno").textContent = d.picks.length + 1;
  $("bar").style.width = `${(d.picks.length / 11) * 100}%`;
  lineChips($("lines"), d.formation, d.picks);
  const expect = movesIn(d.state);
  renderDeal($("deal"), d.deal, {
    heading: "Dealt to the room", rerollsLeft: d.rerolls_left, fresh,
    onTake: (i) => act("pick", { index: i, expect }), onReroll: () => act("reroll", { expect }),
  });
  renderPitch($("pitch"), d.formation.code, d.picks, d.picks.length ? d.picks[d.picks.length - 1].id : null);
  $("xisub").textContent = `${d.picks.length} / 11`;
  xiFoot($("xifoot"), d);
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
