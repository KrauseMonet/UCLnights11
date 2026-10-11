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

function deckCard(cs) {
  const rows = cs.cards.map((c) => `<div class="deck-row">${positionsHtml(c)}
    <span>${esc(c.name)}</span>${rate(c.rating)}</div>`).join("");
  return `<div class="deck-card" style="${teamStyle(cs)}">
    <div class="band">${crest(cs.crest, 64, cs.name)}<div class="deck-year">${esc(cs.season)}</div>
      <div class="deck-name">${esc(cs.name)}</div></div>
    <div class="deck-rows">${rows}</div></div>`;
}

/* The showcase as a stacked deck: the top squad is dealt away and goes to the back, every
   few seconds or on a click. Paused while the pointer rests on it, and never on its own
   for someone who asked for less motion. */
function dealDeck(show) {
  const deck = $("deck"), dots = $("deckdots");
  deck.innerHTML = show.map(deckCard).join("");
  const cards = [...deck.children];
  let top = 0, busy = false, timer = null;
  const place = () => {
    cards.forEach((c, i) => c.dataset.at = (i - top + cards.length) % cards.length);
    dots.innerHTML = cards.map((_, i) => `<i class="${i === top ? "on" : ""}"></i>`).join("");
  };
  const next = () => {
    if (busy) return;
    busy = true;
    const out = cards[top];
    out.classList.add("out");
    setTimeout(() => {
      // Back of the deck without flying across it: snap there unseen, then fade in.
      out.style.transition = "none";
      out.classList.remove("out");
      out.style.opacity = "0";
      top = (top + 1) % cards.length;
      place();
      void out.offsetWidth;
      out.style.transition = out.style.opacity = "";
      busy = false;
    }, 560);
  };
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const run = () => { clearInterval(timer); if (!still) timer = setInterval(next, 4200); };
  deck.onclick = () => { next(); run(); };
  deck.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); next(); run(); } };
  deck.onmouseenter = () => clearInterval(timer);
  deck.onmouseleave = run;
  place();
  run();
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
  $("crestwall").innerHTML = META.crests.map((u) => crest(u, 48)).join("");
  // Each section paints as soon as its own data lands; the deck is small and leads the page,
  // so it must not wait for the archive, which carries every season.
  api("/api/showcase").then(dealDeck).catch(() => {});
  const arch = await api("/api/archive");
  const latest = arch.seasons[0];
  $("latest-sub").innerHTML = `${esc(latest.label)}. Every quarter-finalist since 1994–95 is in the deck. <a href="/archive">See all ${META.club_seasons}</a>.`;
  $("latest").innerHTML = latest.sides.map((s) =>
    `<a href="/archive#${s.key}" style="${teamStyle(s)}">${crest(s.crest, 48, s.name)}<span>${esc(s.name)}</span></a>`).join("");
})();
