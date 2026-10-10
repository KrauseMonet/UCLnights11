"use strict";

shell("archive");

function tile(s) {
  return `<button class="tile" data-key="${s.key}" style="${teamStyle(s)}">
    <div class="band">${crest(s.crest, 48, s.name)}<b>${esc(s.name)}</b></div>
    <div class="foot"><span>${esc(s.star.name)}</span>${rate(s.star.rating)}</div></button>`;
}

async function openSquad(key) {
  const d = await api(`/api/squad/${key}`);
  const byLine = { GK: [], DF: [], MF: [], FW: [] };
  d.cards.forEach((c) => byLine[c.pos].push(c));
  const rows = Object.entries(byLine).filter(([, cs]) => cs.length).map(([pos, cs]) =>
    `<div class="line-h">${LINES[pos]}</div>` + cs.map((c) => `<div class="row">
      <span class="pos ${c.pos}">${c.pos}</span>
      <div class="who"><b>${esc(c.name)}</b><small>${esc(c.nation || "")}</small></div>${rate(c.rating)}</div>`).join("")).join("");
  $("drawer-in").style.cssText = teamStyle(d);
  $("drawer-in").innerHTML = `<div class="band"><button class="close" id="close">Close</button>
      ${crest(d.crest, 84, d.name)}<div class="deal-year" style="font-size:56px">${esc(d.season)}</div>
      <div class="deal-club">${esc(d.name)}</div></div>${rows}`;
  $("drawer").hidden = false;
  history.replaceState(null, "", `#${key}`);
  $("close").onclick = closeSquad;
}

function closeSquad() {
  $("drawer").hidden = true;
  history.replaceState(null, "", location.pathname);
}

$("drawer").onclick = (e) => { if (e.target.id === "drawer") closeSquad(); };
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSquad(); });

(async function boot() {
  loadMeta().catch(() => {});
  const d = await api("/api/archive");
  $("seasons").innerHTML = d.seasons.map((s) => `<section class="season">
    <h2>${esc(s.label)} <small>${s.sides.length} in the deck</small></h2>
    <div class="tiles">${s.sides.map(tile).join("")}</div></section>`).join("");
  $("seasons").onclick = (e) => { const t = e.target.closest(".tile"); if (t) openSquad(t.dataset.key).catch((err) => toast(err.message)); };
  if (d.gaps.length) {
    $("gaps").textContent = `Not in the deck, because Wikipedia has no squad list that can be read for them: ${d.gaps.map((g) => g.replace(" (no article)", "")).join(" · ")}. Milan 2011–12's squad reads only in part, so it is left out rather than half-rated.`;
  }
  const key = location.hash.slice(1);
  if (key) openSquad(key).catch(() => {});
})();
