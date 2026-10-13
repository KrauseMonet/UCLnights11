"use strict";

shell("home");
function deckCard(cs) {
  const rows = cs.cards.map((c) => `<div class="deck-row">${positionsHtml(c)}
    <span>${esc(c.name)}</span>${rate(c.rating)}</div>`).join("");
  const era = eraOf(cs);
  return `<div class="deck-card" style="${teamStyle(cs)}">
    <div class="band ${era.cls}">${crest(cs.crest, 64, cs.name)}${era.mark}<div class="deck-year">${esc(cs.season)}</div>
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

(async function boot() {
  try { await loadMeta(); } catch { toast("Could not reach the server"); return; }
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
