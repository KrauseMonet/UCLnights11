"use strict";
/* One match, played out on screen: the card, the clock, the goals as they go in, the
   statistics building from the shot timeline (C30) and the goal burst. Shared by the
   tournament page and the daily challenge, which differ only in how they name a side
   and label a match, passed in as `look` = { name(side), sub(side), stage(fixture) }.

   Since C60 a match also stops for half-time, with the numbers so far on the card; it
   has sounds (a whistle, the crowd, a goal's roar), synthesized here, so no recording is
   copied from anywhere; and a side that makes its own changes can pause it ("Make a
   sub"), see its eleven and bench, and change them. A live match's fixture may also
   arrive in pieces (`upto`: everything up to that minute, the rest not played yet), as
   the daily's ranked match and a room watching together send it, so nobody can see what
   a change would have spared them. */

const GOAL_PAUSE_MS = 1700;      // the clock stops this long for a goal
const HALF_TIME_MS = 2600;       // and this long at half-time (C60)
const ET_BREAK_MS = 1500;        // and before extra time
// A match sent in pieces asks for its next piece about this long before it runs out: enough
// for a reply to arrive, and no more, since a change comes after everything already sent.
const FEED_AHEAD_MS = 800;

/* ---------------------------------------------------------------- sound (C60)
   Made with the Web Audio API, not recordings: a referee's whistle (a high tone with a
   pea's flutter), the crowd (filtered noise that swells and settles) and a roar for a
   goal. On unless turned off with the speaker chip, which this browser remembers. A
   browser only lets a page make sound after a tap, and every match here starts with one. */
const SOUND = { ctx: null, crowd: null };
const soundOn = () => store.get("sound") !== "off";

function audio() {
  if (!soundOn()) return null;
  try {
    SOUND.ctx ||= new (window.AudioContext || window.webkitAudioContext)();
    if (SOUND.ctx.state === "suspended") SOUND.ctx.resume();
    return SOUND.ctx;
  } catch { return null; }
}

let NOISE = null;
function noise(ctx) {
  if (NOISE) return NOISE;
  const n = ctx.sampleRate * 4, buf = ctx.createBuffer(1, n, ctx.sampleRate), d = buf.getChannelData(0);
  let last = 0;
  for (let i = 0; i < n; i++) { last = (last + 0.02 * (Math.random() * 2 - 1)) / 1.02; d[i] = last * 3.5; }
  return (NOISE = buf);
}

/* "kick" one long blast, "half" two, "full" three, "et" one short. */
function blow(kind) {
  const ctx = audio();
  if (!ctx) return;
  const blasts = { kick: [[0, 0.8]], et: [[0, 0.5]], half: [[0, 0.3], [0.42, 0.75]],
    full: [[0, 0.28], [0.4, 0.28], [0.8, 1.0]] }[kind] || [[0, 0.5]];
  const t0 = ctx.currentTime + 0.02;
  for (const [at, len] of blasts) {
    const o = ctx.createOscillator(), pea = ctx.createOscillator(), depth = ctx.createGain(), g = ctx.createGain();
    o.type = "triangle"; o.frequency.value = 2950;
    pea.frequency.value = 34; depth.gain.value = 160;
    pea.connect(depth).connect(o.frequency);
    const a = t0 + at;
    g.gain.setValueAtTime(0, a);
    g.gain.linearRampToValueAtTime(0.12, a + 0.025);
    g.gain.setValueAtTime(0.12, a + len - 0.06);
    g.gain.linearRampToValueAtTime(0, a + len);
    o.connect(g).connect(ctx.destination);
    o.start(a); pea.start(a); o.stop(a + len + 0.05); pea.stop(a + len + 0.05);
  }
}

function crowdStart() {
  const ctx = audio();
  if (!ctx || SOUND.crowd) return;
  const src = ctx.createBufferSource(), lo = ctx.createBiquadFilter(), hi = ctx.createBiquadFilter(), g = ctx.createGain();
  const swell = ctx.createOscillator(), depth = ctx.createGain();
  src.buffer = noise(ctx); src.loop = true;
  lo.type = "lowpass"; lo.frequency.value = 1100;
  hi.type = "highpass"; hi.frequency.value = 160;
  g.gain.value = 0;
  g.gain.linearRampToValueAtTime(0.055, ctx.currentTime + 1.2);
  swell.frequency.value = 0.11; depth.gain.value = 0.02;
  swell.connect(depth).connect(g.gain);
  src.connect(hi).connect(lo).connect(g).connect(ctx.destination);
  src.start(); swell.start();
  SOUND.crowd = { src, swell, g };
}

function crowdStop() {
  const c = SOUND.crowd, ctx = SOUND.ctx;
  if (!c || !ctx) return;
  SOUND.crowd = null;
  const t = ctx.currentTime;
  c.g.gain.cancelScheduledValues(t);
  c.g.gain.setValueAtTime(c.g.gain.value, t);
  c.g.gain.linearRampToValueAtTime(0, t + 0.8);
  c.src.stop(t + 0.85); c.swell.stop(t + 0.85);
}

function roar() {
  const ctx = audio();
  if (!ctx) return;
  const src = ctx.createBufferSource(), bp = ctx.createBiquadFilter(), g = ctx.createGain(), t = ctx.currentTime;
  src.buffer = noise(ctx);
  bp.type = "bandpass"; bp.frequency.value = 650; bp.Q.value = 0.6;
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(0.42, t + 0.28);
  g.gain.setValueAtTime(0.42, t + 0.9);
  g.gain.exponentialRampToValueAtTime(0.001, t + 3.2);
  src.connect(bp).connect(g).connect(ctx.destination);
  src.start(t, Math.random() * 2); src.stop(t + 3.3);
}

/* The speaker chip, beside the pace. Turning it off silences a crowd already going. */
function soundChip() {
  const on = soundOn();
  return `<button class="chip snd" data-sound aria-pressed="${on}" title="${on ? "Sound on" : "Sound off"}">${on ? "🔊" : "🔇"}<span class="sr">${on ? "Sound on" : "Sound off"}</span></button>`;
}

function wireSound(root, running) {
  root.querySelectorAll("[data-sound]").forEach((b) => b.onclick = () => {
    store.set("sound", soundOn() ? "off" : "on");
    root.querySelectorAll("[data-sound]").forEach((x) => { x.outerHTML = soundChip(); });
    wireSound(root, running);
    if (!soundOn()) crowdStop();
    else if (running()) crowdStart();
  });
}

/* How fast a match you watch alone plays: ms per match minute, so a ninety takes about
   5 s, 13 s or 27 s. Chosen on the card, changeable mid-match, remembered in this browser.
   A room watching together keeps its own shared clock (watch.js), which no one screen can slow. */
const PACES = [["fast", "Fast", 55], ["normal", "Normal", 140], ["slow", "Slow", 300]];
const paceNow = () => PACES.find((p) => p[0] === store.get("pace")) || PACES[0];

function paceHtml(live) {
  const on = paceNow()[0];
  return `<div class="pace">${live ? `<button class="btn ghost makesub" data-makesub>Make a sub</button>` : ""}
    ${soundChip()}<span>Pace</span><div class="chips" role="radiogroup" aria-label="Match pace">${PACES.map(([k, label]) =>
    `<button class="chip" role="radio" aria-checked="${k === on}" data-pace="${k}">${label}</button>`).join("")}</div></div>`;
}

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
const surname = (n) => n.split(" ").length > 1 && !/^(van|von|de|da|di|del|dos|der|den|le|la|ter)$/i.test(n.split(" ").slice(-2, -1)[0]) ? n.split(" ").slice(-1)[0] : n.split(" ").slice(-2).join(" ");

/* Where slot j of side i stands: side on (--hx/--hy) and, on a phone, upright (--vx/--vy). */
function luSpot(spots, j, i) {
  const { x, y } = spots[j];
  const [hx, hy, vx, vy] = i === 0 ? [(100 - y) / 2, x, x, 50 + y / 2] : [50 + y / 2, 100 - x, 100 - x, (100 - y) / 2];
  return `--hx:${hx}%;--hy:${hy}%;--vx:${vx}%;--vy:${vy}%`;
}

function lineupsHtml(f, look) {
  if (!f.lineups) return "";
  const side = (lu, s, i) => {
    const spots = slotSpots(lu.slots), used = new Set();
    const men = lu.slots.map((slot, j) => {
      const k = lu.xi.findIndex((c, n) => c.slot === slot && !used.has(n));
      used.add(k);
      const c = lu.xi[k] || { name: "", slot };
      return `<div class="lu-p" data-side="${i}" data-name="${esc(c.name)}" title="${esc(c.name)} · ${slot}"
        style="${luSpot(spots, j, i)}"><i>${slot}</i><span>${esc(surname(c.name))}</span></div>`;
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

/* A scorer's disc lights up, with a ball for each goal; the man who set it up gets a boot
   for each assist, on the other shoulder. */
const ASSIST_MARK = "👟";
function markDisc(side, name, kind, sign, flash) {
  const p = [...document.querySelectorAll(`.lu-p[data-side="${side}"]`)].find((d) => d.dataset.name === name);
  if (!p) return;
  p.classList.remove(flash); void p.offsetWidth; p.classList.add(flash);
  p.dataset[kind] = (+(p.dataset[kind] || 0) + 1);
  p.querySelector("i").dataset[kind] = sign.repeat(+p.dataset[kind]);
}

function markScorer(g) {
  markDisc(g.side, g.scorer, "goals", "⚽", "scored");
  if (g.assist) markDisc(g.side, g.assist, "assists", ASSIST_MARK, "assisted");
}

/* A substitution (C41): the man coming on takes the disc of the man going off, and anyone
   moved to make room slides to his new place. `x.xi` is the eleven after the change, in
   the formation's slot order. */
function applySub(f, x) {
  if (!f.lineups) return;
  const discs = [...document.querySelectorAll(`.lu-p[data-side="${x.side}"]`)];
  const off = discs.find((d) => d.dataset.name === x.off);
  if (off) {
    off.dataset.name = x.on;
    off.dataset.goals = 0;
    off.dataset.assists = 0;
    delete off.querySelector("i").dataset.goals;
    delete off.querySelector("i").dataset.assists;
    off.querySelector("span").textContent = surname(x.on);
    off.classList.remove("subbed"); void off.offsetWidth; off.classList.add("subbed");
  }
  const lu = f.lineups[x.side], spots = slotSpots(lu.slots);
  x.xi.forEach((c, j) => {
    const d = discs.find((e) => e.dataset.name === c.name);
    if (!d) return;
    d.style.cssText = luSpot(spots, j, x.side);
    d.querySelector("i").textContent = c.slot;
    d.title = `${c.name} · ${c.slot}`;
  });
}

function subLine(x) {
  const who = `${esc(x.on)} <small>for ${esc(x.off)}</small>`;
  return x.side === 0
    ? `<div class="h sub">${who}<span class="m">${x.minute}'</span>⇄</div>`
    : `<div class="a sub">⇄<span class="m">${x.minute}'</span>${who}</div>`;
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
   shots on target and saves as they happened. A live match (C60) carries its passes and
   possession block by block (`flow`), so they are the real running numbers; any other
   match's passes build evenly, since the engine kept their totals, not their moments, and
   its possession drifts round its final figure until the whistle. At full time every
   number is the real one. */
function liveStats(f, minute, end) {
  const st = f.stats, shots = (f.shots || []).filter((x) => x[0] <= minute);
  const count = (side, test) => shots.filter((x) => x[1] === side && test(x)).length;
  const on = [0, 1].map((i) => count(i, (x) => x[2])), goals = [0, 1].map((i) => count(i, (x) => x[3]));
  const out = { shots: [0, 1].map((i) => count(i, () => true)), on_target: on, saves: [on[1] - goals[1], on[0] - goals[0]] };
  if (f.flow && f.flow.length) {
    let prev = [0, f.flow[0][1], 0, 0, 0, 0], at = prev;
    for (const e of f.flow) {
      if (e[0] >= minute) { const t = (minute - prev[0]) / (e[0] - prev[0]); at = prev.map((v, j) => v + (e[j] - v) * t); at[1] = e[1]; break; }
      prev = at = e;
    }
    const ph = Math.round(at[1] * 100);
    return { ...out, possession: [ph, 100 - ph], passes: [Math.round(at[2]), Math.round(at[3])],
      completed: [Math.round(at[4]), Math.round(at[5])] };
  }
  const frac = Math.min(1, minute / end);
  const drift = Math.sin(minute * 0.37 + st.passes[0] % 7) * 6 * (1 - frac);
  const ph = Math.round(Math.min(75, Math.max(25, st.possession[0] + drift)));
  return { ...out, possession: [ph, 100 - ph],
    passes: st.passes.map((n) => Math.round(n * frac)), completed: st.completed.map((n) => Math.round(n * frac)) };
}

/* Half-time (C60): the clock stops and the card shows the score and the numbers so far.
   Also "Extra time" before the thirty more minutes. Removed when the clock goes again. */
function breakCard(f, label, score, minute, end) {
  const card = document.querySelector(".matchcard");
  if (!card) return;
  card.querySelector(".ht-card")?.remove();
  card.querySelector(".goal-burst")?.remove();      // a room's clock can reach the break inside a goal's moment
  const rows = (f.stats || f.flow) ? statRows(f, liveStats(f, minute, end)) : [];
  card.insertAdjacentHTML("beforeend", `<div class="ht-card" role="status" aria-live="polite">
    <div class="ht-word">${esc(label)}</div><div class="ht-score">${esc(score)}</div>
    ${rows.length ? `<div class="ht-rows">${rows.map((r) => `<div><b>${r.h}</b><span>${r.label}</span><b>${r.a}</b></div>`).join("")}</div>` : ""}</div>`);
}
const clearBreak = () => document.querySelector(".matchcard .ht-card")?.remove();

/* A goal: the clock stops and the card fills with the scorer's colours for a moment. */
function goalBurst(f, g, look) {
  const side = g.side === 0 ? f.home : f.away;
  const card = document.querySelector(".matchcard");
  if (!card) return;
  card.querySelector(".goal-burst")?.remove();
  card.insertAdjacentHTML("beforeend", `<div class="goal-burst" style="${teamStyle(side)}" role="status" aria-live="assertive">
    <div class="gb-ball" aria-hidden="true">⚽</div><div class="gb-word">Goal</div>
    <div class="gb-who">${esc(g.scorer)} <span>${g.minute}'</span></div>
    ${g.assist ? `<div class="gb-assist"><span aria-hidden="true">${ASSIST_MARK}</span> assisted by ${esc(g.assist)}</div>` : ""}
    ${g.kind ? `<div class="gb-kind">${esc(kindLabel(g))}</div>` : ""}
    <div class="gb-side">${esc(look.name(side))}</div></div>`);
}

/* How a goal was scored (C61): "Header · from a corner", "Volley · left foot". */
const KIND_WORDS = { header: "Header", penalty: "Penalty", free_kick: "Free kick", long_range: "Long range",
  tap_in: "Tap-in", volley: "Volley", solo_run: "Solo run" };
const MADE_WORDS = { pass: "from a pass", cross: "from a cross", corner: "from a corner", header: "from a knock-down",
  rebound: "from a rebound", free_kick: "from a free kick" };
function kindLabel(g) {
  const foot = g.foot ? `${g.foot} foot` : "";
  const what = g.kind === "foot" ? foot.charAt(0).toUpperCase() + foot.slice(1) : KIND_WORDS[g.kind] || "";
  const how = g.kind === "header" || g.kind === "foot" ? MADE_WORDS[g.made] || "" : g.foot && g.kind !== "foot" ? foot : "";
  return how ? `${what} · ${how}` : what;
}
const kindChip = (g) => g.kind
  ? `<span class="gk">${esc(kindLabel(g))}</span>` : "";
const saidLine = (g) => g.line ? `<span class="said">${kindChip(g)}${esc(g.line)}</span>` : "";

function goalLine(g) {
  const assist = g.assist ? ` <small title="Assist"><span aria-label="assist by">${ASSIST_MARK}</span> ${esc(g.assist)}</small>` : "";
  return g.side === 0
    ? `<div class="h">${esc(g.scorer)}${assist}<span class="m">${g.minute}'</span>⚽${saidLine(g)}</div>`
    : `<div class="a">⚽<span class="m">${g.minute}'</span>${esc(g.scorer)}${assist}${saidLine(g)}</div>`;
}

/* A match on the card that can be moved on to any minute: `to(m, show)` plays every
   change and goal up to minute m and returns the goals it scored (`show` false catches up
   without the flash and the burst, for a screen that arrives mid-match); `whistle()` goes
   to full time, and `onWhistle` runs once, at the whistle either way. Driven by
   playMatch's own clock below, or by the clock a room watches on together (watch.js, C52).

   `update(g)` hands it a newer version of the same match (C60): after a change, or the
   next piece of a match sent in pieces. Everything up to the minute on screen is the same
   in both, which the engine guarantees, so it carries on from where it is. A match in
   pieces (`upto` set) never runs past what it has, and whistles only once it is `done`. */
function matchRunner(host, f, look, onWhistle = () => {}) {
  host.innerHTML = matchCardHtml(f, "0–0", "0'", look);
  const endOf = (x) => x.extra_time ? 120 : 90;
  let end = endOf(f), subs = f.subs || [];
  let minute = 0, h = 0, a = 0, gi = 0, si = 0, over = false;
  const limit = () => f.upto == null ? end : Math.min(f.upto, end);
  const final = () => f.upto == null || f.done;
  // A change after minute m comes before any goal after it, and after a goal in it.
  const nextSub = (upTo) => {
    while (si < subs.length && subs[si].minute <= upTo && !(gi < f.goals.length && f.goals[gi].minute <= subs[si].minute)) {
      const x = subs[si++];
      feed.insertAdjacentHTML("beforeend", subLine(x));
      applySub(f, x);
    }
  };
  const feed = $("feed");
  let live = !!(f.shots && (f.stats || f.flow));
  if (live) { $("mstats").innerHTML = statsHtml(f, liveStats(f, 0, end)); $("mstats").classList.add("live"); }
  const whistle = (natural = false) => {
    if (over) return;
    over = true;
    host.querySelector(".goal-burst")?.remove();
    clearBreak();
    nextSub(end);
    while (gi < f.goals.length) {
      const g = f.goals[gi++];
      feed.insertAdjacentHTML("beforeend", goalLine(g));
      markScorer(g);
      nextSub(end);
    }
    $("sc").textContent = `${f.hg}–${f.ag}`;
    $("clk").textContent = f.pens ? `${f.pens[0]}–${f.pens[1]} on penalties` : f.extra_time ? "After extra time" : "Full time";
    $("tb").style.width = "100%";
    $("mstats").classList.remove("live");
    if (f.stats) $("mstats").innerHTML = statsHtml(f);
    crowdStop();
    if (natural) blow("full");
    onWhistle();
  };
  const to = (m, show = true) => {
    const scored = [];
    if (over) return scored;
    while (minute < Math.min(m, limit())) {
      minute += 1;
      nextSub(minute);
      while (gi < f.goals.length && f.goals[gi].minute <= minute) {
        const g = f.goals[gi++];
        g.side === 0 ? h++ : a++;
        const sc = $("sc");
        sc.textContent = `${h}–${a}`;
        if (show) { sc.classList.remove("flash"); void sc.offsetWidth; sc.classList.add("flash"); }
        feed.insertAdjacentHTML("beforeend", goalLine(g));
        markScorer(g);
        if (show) { goalBurst(f, g, look); roar(); }
        scored.push(g);
        nextSub(minute);
      }
    }
    $("clk").textContent = `${minute}'`;
    $("tb").style.width = `${(minute / end) * 100}%`;
    if (live) updateStats($("mstats"), f, liveStats(f, minute, end));
    if (minute >= end && final()) whistle(show);
    return scored;
  };
  const update = (g) => {
    if (over) return;
    f = g;
    end = endOf(f);
    subs = f.subs || [];
    if (!live && f.shots && (f.stats || f.flow)) {
      live = true;
      $("mstats").innerHTML = statsHtml(f, liveStats(f, minute, end));
      $("mstats").classList.add("live");
    }
    to(minute, false);
  };
  return { to, whistle, update, score: () => `${h}–${a}`,
    get minute() { return minute; }, get over() { return over; }, get end() { return end; },
    get limit() { return limit(); }, get f() { return f; } };
}

/* Play `f` into `host` from kick-off, a minute every pace step (PACES), the clock stopping
   for a goal, for half-time and before extra time. Returns `finish`, which jumps to the
   whistle (`finish.run` is the match on the card); `onDone` runs once, at the whistle either
   way. The pace is read at every step, so a change takes hold at once.

   `opts.live` (C60) puts "Make a sub" on the card for a side that makes its own changes:
   it stops the clock and calls `opts.live.open(minute, run)`, the next break's minute,
   which resolves with the match as it now goes (or null to carry on as it was).
   `opts.feed(run)` fetches the next piece of a match sent in pieces. */
function playMatch(host, f, look, onDone, opts = {}) {
  let timer = null, pausedUntil = 0, held = false, feeding = null, halfDone = false, etDone = false;
  const run = matchRunner(host, f, look, () => { clearTimeout(timer); host.querySelector(".pace")?.remove(); onDone(); });
  host.insertAdjacentHTML("afterbegin", paceHtml(!!opts.live));
  const bar = host.querySelector(".pace");
  const schedule = (ms) => { clearTimeout(timer); if (!run.over && !held) timer = setTimeout(tick, ms); };
  bar.onclick = (e) => {
    const b = e.target.closest("[data-pace]");
    if (!b) return;
    store.set("pace", b.dataset.pace);
    host.querySelectorAll("[data-pace]").forEach((x) => x.setAttribute("aria-checked", x === b));
    schedule(Math.max(0, pausedUntil - Date.now()) || paceNow()[2]);
  };
  wireSound(bar, () => !run.over);
  const more = () => {
    const ahead = Math.max(6, Math.ceil(FEED_AHEAD_MS / paceNow()[2]));
    if (!opts.feed || feeding || run.f.upto == null || run.f.done || run.limit - run.minute > ahead) return;
    feeding = opts.feed(run).then((g) => { if (g) run.update(g); }).catch(() => {}).finally(() => { feeding = null; });
  };
  const tick = () => {
    const now = Date.now();
    if (now >= pausedUntil) {
      if (pausedUntil) { pausedUntil = 0; host.querySelector(".goal-burst")?.remove(); clearBreak(); }
      if (run.minute === 45 && !halfDone) {
        halfDone = true;
        pausedUntil = now + HALF_TIME_MS;
        blow("half");
        breakCard(run.f, "Half-time", run.score(), 45, run.end);
      } else if (run.minute === 90 && run.end === 120 && !etDone) {
        etDone = true;
        pausedUntil = now + ET_BREAK_MS;
        blow("et");
        breakCard(run.f, "Extra time", run.score(), 90, run.end);
      } else {
        more();
        if (run.minute >= run.limit && !run.over) return schedule(200);   // the next piece is on its way
        if (run.to(run.minute + 1).length) pausedUntil = now + GOAL_PAUSE_MS;
      }
    }
    if (!run.over) schedule(pausedUntil > now ? pausedUntil - now : paceNow()[2]);
  };
  const makeSub = async () => {
    if (run.over || held) return;
    held = true;
    clearTimeout(timer);
    const btn = bar.querySelector("[data-makesub]");
    btn.disabled = true;
    host.querySelector(".goal-burst")?.remove();
    clearBreak();
    pausedUntil = 0;
    if (run.minute >= 45) halfDone = true;
    try {
      const g = await opts.live.open(Math.max(5, Math.ceil(run.minute / 5) * 5), run);
      if (g) run.update(g);
    } catch (e) { toast(e.message); }
    finally {
      held = false;
      if (btn.isConnected) btn.disabled = false;
      schedule(paceNow()[2]);
    }
  };
  if (opts.live) bar.querySelector("[data-makesub]").onclick = makeSub;
  blow("kick");
  crowdStart();
  schedule(paceNow()[2]);
  const finish = () => { clearTimeout(timer); run.whistle(); };
  finish.run = run;
  finish.hold = () => { held = true; clearTimeout(timer); };
  finish.go = () => { held = false; schedule(paceNow()[2]); };
  return finish;
}

/* The pause for a change (C60): the eleven on the pitch at the break, the bench, and whom
   each substitute could replace (`o` from the server's options, which the server checks
   again). Resolves with { on, off } (bench index, person) or null for "back to the match". */
function subDialog(o) {
  return new Promise((resolve) => {
    const box = document.createElement("div");
    box.className = "modal sub-modal";
    const left = o.left === 1 ? "1 change left" : `${o.left} changes left`;
    box.innerHTML = `<div class="modal-in" role="dialog" aria-modal="true" aria-labelledby="subh">
      <button class="close" data-x aria-label="Back to the match">✕</button>
      <h2 id="subh">Make a sub</h2>
      <p class="why-sign">${left} · he comes on at ${o.minute}'. The match waits for you.</p>
      <div class="sub-grid"><div class="pitch" id="subpitch"></div>
        <div class="sub-bench" id="subbench">${o.bench.map((c) => `<div class="sub-card filled ${c.used || !c.can_replace.length ? "off" : "pickable"}" data-on="${c.i}" tabindex="0" role="button">
          ${crest(c.crest, 28, c.club)}<div class="who"><b>${esc(c.name)}</b><small>${c.positions.map(posChip).join("")}${c.rating == null ? "" : ` ${c.rating}`}</small>
          ${c.used ? `<small class="note">On already</small>` : !c.can_replace.length ? `<small class="note">Can't come on for anyone in this shape</small>` : ""}</div></div>`).join("")}</div></div>
      <p class="sheet-hint" id="subhint">Choose who comes on, then who he replaces.</p>
      <div class="sub-acts"><button class="btn primary" id="subgo" disabled>Make the change</button>
        <button class="btn ghost" data-x>Back to the match</button></div></div>`;
    document.body.append(box);
    const pitch = $("subpitch"), bench = $("subbench");
    renderPitch(pitch, o.slots, o.pitch, null);
    let on = null, off = null;
    const paint = () => {
      const can = on == null ? [] : o.bench.find((c) => c.i === on).can_replace;
      pitch.classList.toggle("choosing", on != null);
      pitch.querySelectorAll(".slot[data-id]").forEach((el) => {
        el.classList.toggle("pickable", can.includes(el.dataset.id));
        el.classList.toggle("can", can.includes(el.dataset.id) && el.dataset.id !== off);
        el.classList.toggle("sel", el.dataset.id === off);
      });
      bench.querySelectorAll("[data-on]").forEach((el) => el.classList.toggle("sel", +el.dataset.on === on));
      const a = on == null ? null : o.bench.find((c) => c.i === on), b = off && o.pitch.find((c) => c.id === off);
      $("subhint").innerHTML = !a ? "Choose who comes on, then who he replaces."
        : !b ? `<b>${esc(a.name)}</b> could come on for anyone highlighted.` : `<b>${esc(a.name)}</b> on for <b>${esc(b.name)}</b> at ${o.minute}'.`;
      $("subgo").disabled = !(a && b);
    };
    const close = (v) => { box.remove(); resolve(v); };
    bench.querySelectorAll(".pickable[data-on]").forEach((el) => {
      const go = () => { on = on === +el.dataset.on ? null : +el.dataset.on; off = null; paint(); };
      el.onclick = go;
      el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } };
    });
    pitch.querySelectorAll(".slot[data-id]").forEach((el) => {
      el.tabIndex = 0;
      const go = () => { if (el.classList.contains("pickable")) { off = el.dataset.id; paint(); } };
      el.onclick = go;
      el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } };
    });
    box.querySelectorAll("[data-x]").forEach((b) => b.onclick = () => close(null));
    box.onclick = (e) => { if (e.target === box) close(null); };
    box.onkeydown = (e) => { if (e.key === "Escape") close(null); };
    $("subgo").onclick = () => close({ on, off });
    paint();
    box.querySelector("[data-x]").focus();
  });
}

/* Before matches are skipped by a side that makes its own changes (C60): use the plan in
   what is skipped, or make no changes there. Resolves true, false, or null (don't skip). */
function askAutoPlan(what, friends = false) {
  return new Promise((resolve) => {
    const box = document.createElement("div");
    box.className = "modal";
    box.innerHTML = `<div class="modal-in" role="dialog" aria-modal="true" aria-labelledby="autoh">
      <button class="close" data-v="" aria-label="Don't skip">✕</button>
      <h2 id="autoh">${friends ? "Use their sub plans?" : "Use your sub plan?"}</h2>
      <p class="why-sign">${esc(what)} ${friends
        ? "Friends who make their own changes won't be there to make them. Each one's plan can, or nobody comes on for them."
        : "You won't be there to make changes. Your plan can make them for you, or nobody comes on."}</p>
      <div class="sub-acts"><button class="btn primary" data-v="yes">Yes, use the plan</button>
        <button class="btn ghost" data-v="no">No, no changes</button></div></div>`;
    document.body.append(box);
    const close = (v) => { box.remove(); resolve(v); };
    box.querySelectorAll("[data-v]").forEach((b) => b.onclick = () => close(b.dataset.v === "" ? null : b.dataset.v === "yes"));
    box.onclick = (e) => { if (e.target === box) close(null); };
    box.onkeydown = (e) => { if (e.key === "Escape") close(null); };
    box.querySelector("[data-v=yes]").focus();
  });
}
