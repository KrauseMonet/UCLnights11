"use strict";

shell("home");
let FORMATION = store.get("formation") || "433";
let MEMORY = store.get("memory") === "1";

function renderFormations() {
  const box = $("formations");
  box.innerHTML = META.formations.map((f) =>
    `<button class="chip" role="radio" aria-checked="${f.code === FORMATION}" data-f="${f.code}">${esc(f.label)}</button>`).join("");
  box.onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    FORMATION = b.dataset.f;
    store.set("formation", FORMATION);
    renderFormations();
  };
}

function renderMemory() {
  const box = $("memory");
  box.innerHTML = [[false, "Shown"], [true, "Hidden · Memory"]].map(([m, label]) =>
    `<button class="chip" role="radio" aria-checked="${m === MEMORY}" data-m="${m ? 1 : 0}">${label}</button>`).join("");
  box.onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    MEMORY = b.dataset.m === "1";
    store.set("memory", MEMORY ? "1" : "0");
    renderMemory();
  };
}

function fanCard(cs, i) {
  const rows = cs.cards.map((c) => `<div class="fan-row"><span class="pos ${c.pos}">${c.pos}</span>
    <span>${esc(c.name)}</span>${rate(c.rating)}</div>`).join("");
  return `<div class="fan-card fan-${i}" style="${teamStyle(cs)}">
    <div class="band">${crest(cs.crest, 64, cs.name)}<div class="fan-name">${esc(cs.name)}</div>
      <div class="fan-year">${esc(cs.season)}</div></div>
    <div class="fan-rows">${rows}</div></div>`;
}

$("start").onclick = async (e) => {
  e.target.disabled = true;
  try {
    const q = MEMORY ? "?memory=1" : "";
    const s = await api(`/api/draft${q}`, { method: "POST", body: JSON.stringify({ formation: FORMATION }) });
    location.href = `/draft${q}#${s.state}`;
  } catch (err) { toast(err.message); e.target.disabled = false; }
};

(async function boot() {
  renderMemory();
  try { await loadMeta(); } catch { toast("Could not reach the server"); return; }
  if (!META.formations.some((f) => f.code === FORMATION)) FORMATION = META.default_formation;
  renderFormations();
  $("stats").innerHTML = [
    [META.seasons, "Seasons"], [META.club_seasons, "Squads"], [META.clubs, "Clubs"],
    [META.cards.toLocaleString(), "Players"],
  ].map(([n, l]) => `<div><b>${n}</b>${l}</div>`).join("");
  const crests = META.crests.map((u) => crest(u, 48)).join("");
  $("marquee").innerHTML = crests + crests;     // twice, so the roll loops seamlessly
  // Each section paints as soon as its own data lands; the fan is small and leads the page,
  // so it must not wait for the archive, which carries every season.
  api("/api/showcase").then((show) => { $("fan").innerHTML = show.map(fanCard).join(""); }).catch(() => {});
  const arch = await api("/api/archive");
  const latest = arch.seasons[0];
  $("latest-sub").innerHTML = `${esc(latest.label)}. Every quarter-finalist since 1994–95 is in the deck. <a href="/archive">See all ${META.club_seasons}</a>.`;
  $("latest").innerHTML = latest.sides.map((s) =>
    `<a href="/archive#${s.key}" style="${teamStyle(s)}">${crest(s.crest, 64, s.name)}<span>${esc(s.name)}</span></a>`).join("");
})();
