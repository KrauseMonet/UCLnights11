"use strict";
/* One match, played out on screen: the card, the clock, the goals as they go in, the
   statistics building from the shot timeline (C30) and the goal burst. Shared by the
   tournament page and the daily challenge, which differ only in how they name a side
   and label a match, passed in as `look` = { name(side), sub(side), stage(fixture) }. */

const MINUTE_MS = 55;
const GOAL_PAUSE_MS = 1700;      // the clock stops this long for a goal

function sideCardHtml(s, look) {
  return `<div class="side band" style="${teamStyle(s)}">${sideCrest(s, 84)}
    <div><b>${esc(look.name(s))}</b><br><small>${esc(look.sub(s))}</small></div></div>`;
}

function matchCardHtml(f, score, clock, look) {
  return `<div class="matchcard">
    ${sideCardHtml(f.home, look)}
    <div class="mid"><div class="stage-tag">${esc(look.stage(f))}</div>
      <div class="score" id="sc">${score}</div><div class="clock" id="clk">${clock}</div></div>
    ${sideCardHtml(f.away, look)}
    ${lineupsHtml(f, look)}
    <div class="timebar"><i id="tb"></i></div>
    <div class="feed" id="feed"></div>
    <div class="mstats-wrap" id="mstats"></div></div>`;
}

/* Both elevens on one pitch, as a broadcast shows them before kick-off (C38): home in the
   left half attacking right, away in the right half attacking left; on a phone the pitch
   stands up, home at the bottom. Each man carries both sets of coordinates and the
   stylesheet picks one. Positions come from the formation's slots (game.positions), the
   same drawing as the draft's pitch, turned on its side. */
function lineupsHtml(f, look) {
  if (!f.lineups) return "";
  const surname = (n) => n.split(" ").length > 1 && !/^(van|von|de|da|di|del|dos|der|den|le|la|ter)$/i.test(n.split(" ").slice(-2, -1)[0]) ? n.split(" ").slice(-1)[0] : n.split(" ").slice(-2).join(" ");
  const side = (lu, s, i) => {
    const spots = slotSpots(lu.slots), used = new Set();
    const men = lu.slots.map((slot, j) => {
      const k = lu.xi.findIndex((c, n) => c.slot === slot && !used.has(n));
      used.add(k);
      const c = lu.xi[k] || { name: "", slot }, { x, y } = spots[j];
      const [hx, hy, vx, vy] = i === 0 ? [(100 - y) / 2, x, x, 50 + y / 2] : [50 + y / 2, 100 - x, 100 - x, (100 - y) / 2];
      return `<div class="lu-p" data-side="${i}" data-name="${esc(c.name)}" title="${esc(c.name)} · ${slot}"
        style="--hx:${hx}%;--hy:${hy}%;--vx:${vx}%;--vy:${vy}%"><i>${slot}</i><span>${esc(surname(c.name))}</span></div>`;
    }).join("");
    return `<div class="lu-side" style="${teamStyle(s)}">${men}</div>`;
  };
  const [h, a] = f.lineups;
  return `<div class="lineups" aria-label="Both elevens">
    <div class="lu-head"><span class="lu-h" style="${teamStyle(f.home)}"><b>${esc(look.name(f.home))}</b> · ${esc(h.formation)}</span>
      <span class="lu-a" style="${teamStyle(f.away)}">${esc(a.formation)} · <b>${esc(look.name(f.away))}</b></span></div>
    <div class="lu-pitch"><i class="lu-mark half"></i><i class="lu-mark circle"></i><i class="lu-mark box a"></i><i class="lu-mark box b"></i>
      ${side(h, f.home, 0)}${side(a, f.away, 1)}</div></div>`;
}

/* A scorer's disc lights up, with a ball for each goal. */
function markScorer(g) {
  const p = [...document.querySelectorAll(`.lu-p[data-side="${g.side}"]`)].find((d) => d.dataset.name === g.scorer);
  if (!p) return;
  p.classList.remove("scored"); void p.offsetWidth; p.classList.add("scored");
  p.dataset.goals = (+(p.dataset.goals || 0) + 1);
  p.querySelector("i").dataset.goals = "⚽".repeat(+p.dataset.goals);
}

/* A broadcast-style stats panel: home on the left, away on the right, a split bar per
   row. Built live from the shot timeline while a match plays, final at the whistle. */
const STAT_ROWS = [
  ["possession", "Possession", (v) => `${v}%`],
  ["shots", "Shots"], ["on_target", "On target"],
  ["passes", "Passes"], ["completed", "Passes completed"],
  ["accuracy", "Pass accuracy", (v) => `${v}%`],
  ["saves", "Saves"],
];

function statRows(f, st) {
  const acc = [0, 1].map((i) => st.passes[i] ? Math.round((st.completed[i] / st.passes[i]) * 100) : 0);
  const rows = { ...st, accuracy: acc };
  return STAT_ROWS.map(([k, label, fmt = String]) => {
    const [h, a] = rows[k], total = h + a;
    return { k, label, h: fmt(h), a: fmt(a), hw: total ? (h / total) * 100 : 50, lead: h > a ? "h" : a > h ? "a" : "" };
  });
}

function statsHtml(f, st = f.stats) {
  if (!st) return "";
  // Two sides in one colour (two reds, say) would make the bars unreadable; the away
  // side then takes its lighter ink colour.
  const away = f.away.team.toLowerCase() === f.home.team.toLowerCase() ? f.away.ink : f.away.team;
  return `<div class="mstats" style="--home:${f.home.team};--away:${away}">${statRows(f, st).map((r) =>
    `<div class="mstat" data-k="${r.k}"><b class="${r.lead === "h" ? "lead" : ""}">${r.h}</b><span>${r.label}</span><b class="${r.lead === "a" ? "lead" : ""}">${r.a}</b>
      <div class="split" aria-hidden="true"><i style="width:${r.hw}%"></i><i style="width:${100 - r.hw}%"></i></div></div>`).join("")}</div>`;
}

/* Change the numbers of a panel already on screen, so its bars slide rather than redraw. */
function updateStats(el, f, st) {
  statRows(f, st).forEach((r) => {
    const row = el.querySelector(`[data-k="${r.k}"]`);
    if (!row) return;
    const [h, , a] = row.children, [ih, ia] = row.querySelectorAll(".split i");
    h.textContent = r.h; a.textContent = r.a;
    h.className = r.lead === "h" ? "lead" : ""; a.className = r.lead === "a" ? "lead" : "";
    ih.style.width = `${r.hw}%`; ia.style.width = `${100 - r.hw}%`;
  });
}

/* The numbers at a given minute, replayed from the match's shot timeline (C30): shots,
   shots on target and saves as they happened. Passes build evenly through the match,
   since the engine keeps their totals, not their moments, and possession drifts
   round its final figure until the whistle. At full time every number is the real one. */
function liveStats(f, minute, end) {
  const st = f.stats, shots = (f.shots || []).filter((x) => x[0] <= minute);
  const count = (side, test) => shots.filter((x) => x[1] === side && test(x)).length;
  const on = [0, 1].map((i) => count(i, (x) => x[2])), goals = [0, 1].map((i) => count(i, (x) => x[3]));
  const frac = Math.min(1, minute / end);
  const drift = Math.sin(minute * 0.37 + st.passes[0] % 7) * 6 * (1 - frac);
  const ph = Math.round(Math.min(75, Math.max(25, st.possession[0] + drift)));
  return {
    possession: [ph, 100 - ph], shots: [0, 1].map((i) => count(i, () => true)), on_target: on,
    passes: st.passes.map((n) => Math.round(n * frac)), completed: st.completed.map((n) => Math.round(n * frac)),
    saves: [on[1] - goals[1], on[0] - goals[0]],
  };
}

/* A goal: the clock stops and the card fills with the scorer's colours for a moment. */
function goalBurst(f, g, look) {
  const side = g.side === 0 ? f.home : f.away;
  const card = document.querySelector(".matchcard");
  if (!card) return;
  card.querySelector(".goal-burst")?.remove();
  card.insertAdjacentHTML("beforeend", `<div class="goal-burst" style="${teamStyle(side)}" role="status" aria-live="assertive">
    <div class="gb-ball" aria-hidden="true">⚽</div><div class="gb-word">Goal</div>
    <div class="gb-who">${esc(g.scorer)} <span>${g.minute}'</span></div>
    ${g.assist ? `<div class="gb-assist">assisted by ${esc(g.assist)}</div>` : ""}
    <div class="gb-side">${esc(look.name(side))}</div></div>`);
}

function goalLine(g) {
  const assist = g.assist ? ` <small>(${esc(g.assist)})</small>` : "";
  return g.side === 0
    ? `<div class="h">${esc(g.scorer)}${assist}<span class="m">${g.minute}'</span>⚽</div>`
    : `<div class="a">⚽<span class="m">${g.minute}'</span>${esc(g.scorer)}${assist}</div>`;
}

/* Play `f` into `host` from kick-off. Returns `finish`, which jumps to the whistle;
   `onDone` runs once, at the whistle either way. */
function playMatch(host, f, look, onDone) {
  host.innerHTML = matchCardHtml(f, "0–0", "0'", look);
  const end = f.extra_time ? 120 : 90;
  let minute = 0, h = 0, a = 0, gi = 0, pausedUntil = 0, done = false;
  const feed = $("feed"), live = f.stats && f.shots;
  if (live) { $("mstats").innerHTML = statsHtml(f, liveStats(f, 0, end)); $("mstats").classList.add("live"); }
  const finish = () => {
    if (done) return;
    done = true;
    clearInterval(timer);
    host.querySelector(".goal-burst")?.remove();
    while (gi < f.goals.length) { const g = f.goals[gi++]; feed.insertAdjacentHTML("beforeend", goalLine(g)); markScorer(g); }
    $("sc").textContent = `${f.hg}–${f.ag}`;
    $("clk").textContent = f.pens ? `${f.pens[0]}–${f.pens[1]} on penalties` : f.extra_time ? "After extra time" : "Full time";
    $("tb").style.width = "100%";
    $("mstats").classList.remove("live");
    $("mstats").innerHTML = statsHtml(f);
    onDone();
  };
  const timer = setInterval(() => {
    const now = Date.now();
    if (now < pausedUntil) return;                  // a goal is being celebrated
    if (pausedUntil) { pausedUntil = 0; host.querySelector(".goal-burst")?.remove(); }
    minute += 1;
    $("clk").textContent = `${minute}'`;
    $("tb").style.width = `${(minute / end) * 100}%`;
    while (gi < f.goals.length && f.goals[gi].minute <= minute) {
      const g = f.goals[gi++];
      g.side === 0 ? h++ : a++;
      const sc = $("sc");
      sc.textContent = `${h}–${a}`;
      sc.classList.remove("flash"); void sc.offsetWidth; sc.classList.add("flash");
      feed.insertAdjacentHTML("beforeend", goalLine(g));
      markScorer(g);
      goalBurst(f, g, look);
      pausedUntil = now + GOAL_PAUSE_MS;
    }
    if (live) updateStats($("mstats"), f, liveStats(f, minute, end));
    if (minute >= end) finish();
  }, MINUTE_MS);
  return finish;
}
