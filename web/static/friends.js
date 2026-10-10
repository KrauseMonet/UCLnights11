"use strict";
/* The friends hub: sign in, start a room in one of the five formats, join one by code,
   and get back to the rooms you are already in. */

shell("friends");

const FORMATS = [
  { size: 2, name: "The final", rounds: "One match, neutral ground" },
  { size: 4, name: "4-team cup", rounds: "Semi-finals, final" },
  { size: 8, name: "8-team cup", rounds: "Quarter-finals onwards" },
  { size: 16, name: "16-team cup", rounds: "Round of 16 onwards" },
  { size: 32, name: "32-team tournament", rounds: "Eight groups, then knockouts" },
];
const STATUS = { lobby: "In the lobby", drafting: "Drafting", complete: "Finished" };
let size = +(store.get("room-size") || 8);
let formation = store.get("formation") || "433";

function chips(el, items, current, pick) {
  el.innerHTML = items.map((x) => `<button class="chip" role="radio" aria-checked="${x.code === current}" data-c="${x.code}">${esc(x.label)}</button>`).join("");
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { pick(b.dataset.c); chips(el, items, b.dataset.c, pick); });
}

function renderFormats() {
  $("formats").innerHTML = FORMATS.map((f) => `
    <button class="fmt" role="radio" aria-checked="${f.size === size}" data-s="${f.size}">
      <b>${f.size}</b><span>${esc(f.name)}</span><small>${esc(f.rounds)}</small></button>`).join("");
  $("formats").querySelectorAll(".fmt").forEach((b) => b.onclick = () => {
    size = +b.dataset.s; store.set("room-size", size); renderFormats();
  });
  $("fmtnote").textContent = `up to ${size} players`;
}

async function renderMine() {
  try {
    const { rooms } = await api("/api/rooms");
    if (!rooms.length) return;
    $("mine").innerHTML = rooms.map((r) => `<a class="myroom" href="/room#${r.code}">
      <span class="code-sm">${esc(r.code)}</span>
      <span>${esc(FORMATS.find((f) => f.size === r.size).name)}<small>${r.players} of ${r.size} players${r.host ? " · you host" : ""}</small></span>
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
    const room = await api("/api/rooms", { method: "POST", body: JSON.stringify({ size, formation }) });
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
  if (meta) chips($("formations"), meta.formations, formation, (c) => { formation = c; store.set("formation", c); });
  onAuth(render);
})();
