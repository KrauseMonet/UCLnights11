"use strict";
/* The friends hub: sign in, start a room in one of the five formats, join one by code,
   and get back to the rooms you are already in. */

shell("friends");

const FORMATS = [
  { size: 2, name: "The final", rounds: "One match, neutral ground" },
  { size: 4, name: "4-team cup", rounds: "Semi-finals, final" },
  { size: 8, name: "8-team cup", rounds: "Quarter-finals onwards" },
  { size: 16, name: "16-team cup", rounds: "Round of 16 onwards" },
  { size: 36, name: "36-team league", rounds: "League phase, then knockouts" },
];
// A room of 32 is one made before the league phase (C50): no longer offered, still named.
const NAMES = { ...Object.fromEntries(FORMATS.map((f) => [f.size, f.name])), 32: "32-team tournament" };
const STATUS = { lobby: "In the lobby", drafting: "Drafting", complete: "Finished" };
let size = +(store.get("room-size") || 8);
if (!FORMATS.some((f) => f.size === size)) size = 8;    // a size remembered from before
let formation = store.get("formation") || "433";
let memory = store.get("memory") === "1";
const RATINGS = [{ code: "0", label: "Shown" }, { code: "1", label: "Hidden · Memory" }];
const STYLES = [{ code: "turns", label: "Take turns · shared pool" }, { code: "own", label: "Own pace" },
  { code: "sealed", label: "Auction · sealed bids" }, { code: "open", label: "Auction · open" }];
// The clock each style runs (C70): a pick, a sealed round's market, an open auction's nomination.
const CLOCKS = { turns: [[15, 30, 45], "a pick", 30], open: [[15, 30, 45], "to nominate", 30], sealed: [[30, 45, 60], "a round", 45] };
const OPEN_SIZES = [2, 4, 8];   // game.open_auction.ROOM_SIZES: a bigger room would take well over an hour
let style = store.get("room-style") || "turns";
let timer = +(store.get("room-timer") || 30);
if (!STYLES.some((s) => s.code === style)) style = "turns";

function chips(el, items, current, pick) {
  el.innerHTML = items.map((x) => `<button class="chip" role="radio" aria-checked="${x.code === current}" data-c="${x.code}">${esc(x.label)}</button>`).join("");
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { pick(b.dataset.c); chips(el, items, b.dataset.c, pick); });
}

/* How the room drafts, and its clock. An open auction is offered to rooms of up to eight;
   chosen for a bigger room, it falls back to sealed bids. */
function renderStyles() {
  if (style === "open" && !OPEN_SIZES.includes(size)) style = "sealed";
  const offered = STYLES.map((s) => s.code === "open" && !OPEN_SIZES.includes(size)
    ? { ...s, label: "Auction · open (8 players at most)", off: true } : s);
  chips($("styles"), offered, style, (c) => {
    if (offered.find((s) => s.code === c).off) { toast("An open auction is for rooms of up to 8: a bigger room would take well over an hour. Sealed bids work for any size."); return renderStyles(); }
    style = c; store.set("room-style", c); renderStyles();
  });
  $("styles").querySelectorAll(".chip").forEach((b, k) => { if (offered[k].off) b.classList.add("off"); });
  const clock = CLOCKS[style];
  $("timerrow").hidden = !clock;
  if (!clock) {
    if (![15, 30, 45].includes(timer)) timer = 30;     // own pace keeps a pick clock's choices
    return;
  }
  if (!clock[0].includes(timer)) timer = clock[2];
  chips($("timers"), clock[0].map((t) => ({ code: String(t), label: `${t}s ${clock[1]}` })), String(timer),
    (c) => { timer = +c; store.set("room-timer", c); });
}

function renderFormats() {
  $("formats").innerHTML = FORMATS.map((f) => `
    <button class="fmt" role="radio" aria-checked="${f.size === size}" data-s="${f.size}">
      <b>${f.size}</b><span>${esc(f.name)}</span><small>${esc(f.rounds)}</small></button>`).join("");
  $("formats").querySelectorAll(".fmt").forEach((b) => b.onclick = () => {
    size = +b.dataset.s; store.set("room-size", size); renderFormats(); renderStyles();
  });
  const f = FORMATS.find((x) => x.size === size);
  $("fmtnote").textContent = `up to ${size} players`;
  $("fmtdesc").innerHTML = `<b>${esc(f.name)}</b> · ${esc(f.rounds)}`;
}

async function renderMine() {
  try {
    const { rooms } = await api("/api/rooms");
    if (!rooms.length) return;
    $("mine").innerHTML = rooms.map((r) => `<a class="myroom" href="/room#${r.code}">
      <span class="code-sm">${esc(r.code)}</span>
      <span>${esc(NAMES[r.size] || `${r.size}-team`)}<small>${r.players} of ${r.size} players${r.host ? " · you host" : ""}</small></span>
      <span class="pill ${r.status}">${STATUS[r.status]}</span></a>`).join("");
  } catch (e) { /* the list is a convenience; the page works without it */ }
}

function render(me) {
  $("play").hidden = !me;
  $("gate").innerHTML = me ? "" : `<section class="panel gate">
    <div><h2>Sign in to play with friends</h2>
      <p>A room needs to know whose eleven is whose. The solo draft never asks.</p></div>
    <div class="gate-cta"><button class="btn primary" id="gin">Sign in</button>
      <button class="btn ghost" id="gup">Create an account</button></div></section>`;
  if (!me) {
    $("gin").onclick = () => openAuth("in");
    $("gup").onclick = () => openAuth("up");
    return;
  }
  renderMine();
}

$("create").onclick = async () => {
  $("create").disabled = true;
  try {
    const room = await api("/api/rooms", { method: "POST", body: JSON.stringify({ size, formation, memory, style, timer }) });
    location.href = `/room#${room.code}`;
  } catch (e) { toast(e.message); $("create").disabled = false; }
};

$("join").onsubmit = (e) => {
  e.preventDefault();
  const code = $("code").value.trim().toUpperCase();
  if (!/^[A-Z0-9]{6}$/.test(code)) return toast("A room code is six letters and numbers");
  location.href = `/room?join=1#${code}`;
};
$("code").oninput = () => { $("code").value = $("code").value.toUpperCase(); };

(async function boot() {
  renderFormats();
  const meta = await loadMeta().catch(() => null);
  if (meta) {
    const by = Object.fromEntries(meta.formations.map((f) => [f.code, f]));
    if (!by[formation]) formation = meta.default_formation;
    $("shapebox").innerHTML = shapeBox("newshape");
    const show = (f) => showShape("newshape", f);
    chips($("formations"), meta.formations, formation, (c) => { formation = c; store.set("formation", c); show(by[c]); });
    previewOnHover($("formations"), by, "data-c", show, () => formation);
    show(by[formation]);
  }
  chips($("ratings"), RATINGS, memory ? "1" : "0", (c) => { memory = c === "1"; store.set("memory", c); });
  renderStyles();
  onAuth(render);
})();
