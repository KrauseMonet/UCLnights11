"use strict";
/* Dynasty mode (C64): one squad over ten seasons. The whole dynasty lives in the URL hash
   (game.dynasty's state string); the server replays it on every request and keeps nothing.
   This page drafts the current season (the first draft, then each transfer window), shows
   how last season's squad came into this one, and sends each season to the cup page to be
   played (/cup?season=N). A season's result shows here only once it has been watched
   there, so nothing is spoiled; once a season has begun, its sheet and plan stay as played. */

shell("draft");
let S = null;
let busy = false;
let RECORDS = {};          // season number -> its record, for seasons watched to the end
let LEGACY = null;         // legends, the best eleven and top scorers over those seasons (C66)
let justPicked = false;
const STATE_IN = location.hash.slice(1);
// Set by the cup page: how many of your matches have been seen, and once all of them have.
const seenKey = (st) => `dynseen:${st}`;
const doneKey = (st) => `dyndone:${st}`;
const watched = (st) => store.get(doneKey(st)) === "1";
const begun = (st) => watched(st) || +(store.get(seenKey(st)) || 0) > 0;
const D = () => S.dynasty;
const current = () => D().seasons[D().seasons.length - 1];
const SHORT = { "Champions": "Champions", "Runners-up": "Runners-up", "Semi-finals": "Semi-finals",
  "Quarter-finals": "Quarter-finals", "Round of 16": "Last 16", "Knockout play-offs": "Play-offs", "League phase": "League phase" };

function setSession(s, fresh = true) {
  S = s;
  history.replaceState(null, "", `/dynasty#${s.state}`);
  render(fresh);
}

function render(fresh) {
  const n = D().season;
  $("year").textContent = `Year ${n}`;
  renderYears();
  renderLegacy();
  renderWindow();
  lineChips($("lines"), S.formation, S.xi);
  if (S.complete) return renderSeason();
  const filled = S.picks.length + S.waiting.length;
  const forBench = S.picks.length >= 11;
  $("progtext").innerHTML = n === 1
    ? `Pick <b>${S.picks.length + 1}</b> of ${S.total} · ${esc(S.formation.label)}`
    : `Transfer window · <b>${S.total - filled}</b> to sign · ${esc(S.formation.label)}`;
  $("bar").style.width = `${(filled / S.total) * 100}%`;
  renderDeal($("deal"), S.deal, {
    rerollsLeft: S.rerolls_left, fresh,
    heading: forBench ? `For your bench · ${S.picks.length - 10} of ${S.bench_size}` : n > 1 ? `Year ${n} · dealt to you` : undefined,
    takeLabel: forBench ? "Bench" : undefined,
    onTake: (i) => move("pick", { index: i }), onReroll: () => move("reroll"),
  });
  renderPitch($("pitch"), S.formation.slots, S.xi, justPicked && !forBench ? S.picks[S.picks.length - 1].id : null);
  // The kept substitutes join the squad once the eleven is full; until then they wait here.
  renderBench($("bench"), [...S.bench, ...S.waiting], S.bench_size);
  // On a phone the peek floats under the nav once the deal and pitch are out of sight; with
  // the summer's review open above them that is the whole top of the page, title included.
  pitchPeek(D().reshape ? null : $("pitch"), S);
  $("xisub").textContent = `${S.xi.length} / 11 · bench ${S.bench.length + S.waiting.length} / ${S.bench_size}`;
  xiFoot($("xifoot"), { ...S, picks: S.picks.slice(0, 11) });
  justPicked = false;
}

// --------------------------------------------------------------- the seasons strip

function renderYears() {
  const d = D();
  const titles = Object.values(RECORDS).filter((r) => r.reached === "Champions").length;
  const shown = Math.max(d.length, d.seasons.length);
  $("years").innerHTML = `<div class="dyn-titles"><span class="label">Titles</span><b>${titles}</b></div>`
    + Array.from({ length: shown }, (_, k) => {
      const x = d.seasons[k], n = k + 1, r = RECORDS[n];
      if (!x) return `<div class="dyn-year future"><span class="label">Year ${n}</span><b>–</b></div>`;
      const here = n === d.season;
      const what = r ? SHORT[r.reached] || r.reached : here ? (x.complete ? (begun(x.state) ? "Playing" : "Ready") : "Drafting") : "Not watched";
      const sub = r ? `${r.w}W ${r.d}D ${r.l}L` : x.formation;
      const inner = `<span class="label">Year ${n}</span><b>${esc(what)}</b><small>${esc(sub)}</small>`;
      const cls = `dyn-year${here ? " on" : ""}${r && r.reached === "Champions" ? " champ" : ""}`;
      return x.complete ? `<a class="${cls}" href="/cup?season=${n}#${S.state}">${inner}</a>` : `<div class="${cls}">${inner}</div>`;
    }).join("");
  const on = $("years").querySelector(".on");
  if (on) on.scrollIntoView({ block: "nearest", inline: "nearest" });
}

// --------------------------------------------------------------- the transfer window

const NUMBER = { 2: "two", 3: "three", 4: "four", 7: "seven" };
const ordinal = (n) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th"}`;
const REASON = {
  left: (f) => `No squad in the deck lists him in the ${NUMBER[D().jump] || D().jump} seasons after ${esc(f.from.season)}: the deck holds quarter-finalists only.`,
  end: () => `The deck ends with ${esc(D().deck_ends)}, so it has no next season for him.`,
  "no place": (f) => f.to.positions.some((p) => S.formation.slots.includes(p))
    ? `Every place he could take in the ${esc(S.formation.label)} went to a better-rated man, and the bench holds three.`
    : `In ${esc(f.to.season)} he played ${f.to.positions.map(posChip).join(" ")}, and a ${esc(S.formation.label)} has none of that. Another shape may keep him.`,
};

function fateRow(f, d) {
  const c = f.to || f.from;
  const delta = f.to ? f.to.rating - f.from.rating : 0;
  const change = f.to ? `<span class="dyn-delta ${delta > 0 ? "up" : delta < 0 ? "down" : ""}">${f.from.rating} → ${f.to.rating}</span>` : "";
  let note = "";
  if (f.reason === "carried" || f.reason === "skipped" || f.reason === "released") {
    note = `${esc(f.from.season)} → ${esc(f.to.season)}`;
    if (f.jump > 1) note += ` · ${f.jump - 1 === 1 ? "a season" : `${f.jump - 1} seasons`} skipped`;
    if (f.moved) note += ` · now at ${esc(f.to.club)}`;
    const run = f.reason === "released" ? 0 : D().runs[f.to.id] || 0;
    if (run > 1) note += ` · ${ordinal(run)} season with you`;
  } else {
    note = REASON[f.reason](f);
  }
  const canRelease = d.reshape && f.to && f.reason !== "no place"
    && (f.reason === "released" || d.released.length < d.releases);
  const toggle = canRelease
    ? `<button class="btn small ${f.reason === "released" ? "" : "ghost"}" data-rel="${f.i}">${f.reason === "released" ? "Keep him" : "Release"}</button>` : "";
  const legend = f.to && f.reason !== "released" && (D().runs[f.to.id] || 0) >= D().legend;
  return `<div class="fate ${f.reason.replace(" ", "-")}">${crest(c.crest, 36, c.club)}
    <div class="who"><b>${esc(c.name)}${legend ? ` <span class="dyn-star" title="A legend: ${D().legend} seasons in a row with you">★ Legend</span>` : ""}</b><small>${positionsHtml(c)} ${note}</small></div>${change}${toggle}</div>`;
}

function renderWindow() {
  const d = D(), el = $("window");
  el.hidden = d.season === 1;
  if (el.hidden) return;
  const groups = [
    ["Staying", d.fates.filter((f) => f.reason === "carried" || f.reason === "skipped")],
    ["Released", d.fates.filter((f) => f.reason === "released")],
    ["Leaving", d.fates.filter((f) => ["left", "end", "no place"].includes(f.reason))],
  ].filter(([, fs]) => fs.length);
  const stay = groups.find(([t]) => t === "Staying");
  const summary = `${stay ? stay[1].length : 0} of ${d.fates.length} stay · ${d.released.length} released`;
  const shapes = d.reshape && META ? `<div class="dyn-shapes"><span class="label">Formation for Year ${d.season}</span>
      <div class="chips" role="radiogroup" aria-label="Formation">${META.formations.map((f) =>
        `<button class="chip" role="radio" data-f="${f.code}" aria-checked="${f.code === S.formation.code}">${esc(f.label)}</button>`).join("")}</div></div>` : "";
  el.innerHTML = `<details ${d.reshape ? "open" : ""}>
    <summary class="panel-h"><span class="label">Year ${d.season} · how your squad came through the summer</span><span class="label">${summary}</span></summary>
    <div class="dyn-intro"><p>Every player moves on to his next season in the deck, within ${NUMBER[d.jump] || d.jump} seasons, at that season's rating and with that season's club.
      If no squad lists him, he leaves. ${d.reshape
        ? `Before your first pick you can release up to ${d.releases} (their places are filled from the deals, so it's a gamble) and change the formation.`
        : "The window is open: its releases and formation are settled."}</p></div>
    ${shapes}
    ${groups.map(([title, fs]) => `<div class="dyn-group"><div class="line-h">${title}</div>${fs.map((f) => fateRow(f, d)).join("")}</div>`).join("")}
  </details>`;
  el.querySelectorAll("[data-rel]").forEach((b) => b.onclick = () => {
    const i = +b.dataset.rel;
    const rel = d.released.includes(i) ? d.released.filter((x) => x !== i) : [...d.released, i];
    postWindow(S.formation.code, rel, true);
  });
  el.querySelectorAll("[data-f]").forEach((b) => b.onclick = () => {
    if (b.dataset.f !== S.formation.code) postWindow(b.dataset.f, d.released, true);
  });
}

// --------------------------------------------------------------- a finished squad

function namedPlan() {
  return (S.plan || []).map((x) => ({ on: S.bench[x.on].name, minute: x.minute, when: x.when,
    off: x.off == null ? null : S.xi[x.off].name }));
}

function renderSeason() {
  pitchPeek(null);
  const d = D(), n = d.season, st = current().state;
  $("progtext").innerHTML = `Squad complete · ${esc(S.formation.label)}`;
  $("bar").style.width = "100%";
  renderPitch($("pitch"), S.formation.slots, S.xi, null);
  renderBench($("bench"), S.bench, S.bench_size);
  $("xisub").textContent = `11 / 11 · bench ${S.bench.length} / ${S.bench_size}`;
  xiFoot($("xifoot"), { ...S, picks: S.xi });
  const play = `/cup?season=${n}#${S.state}`;
  const more = n < d.max;
  const next = more ? `<button class="btn primary" id="next">${n >= d.length ? `Carry on: Year ${n + 1}` : `Next season: Year ${n + 1}`}</button>` : "";
  if (begun(st)) {
    // Played (or being played): the sheet and plan stay as they were, since a new one is
    // a new tournament for a season already seen.
    if ($("sheethint")) $("sheethint").remove();
    const r = RECORDS[n];
    const done = watched(st);
    const end = n === d.length && done
      ? (() => { const n = Object.values(RECORDS).filter((x) => x.reached === "Champions").length;
          return `<p class="dyn-end">Ten seasons done: ${n} title${n === 1 ? "" : "s"}. Carry on if you like.</p>`; })() : "";
    $("deal").style.cssText = "";
    $("deal").innerHTML = `<div class="panel-h"><span class="label">Year ${n}</span><span class="label">${r ? esc(r.reached) : "being played"}</span></div>
      <div class="dyn-season">${r ? `<p class="dyn-result">${esc(SHORT[r.reached] || r.reached)} · ${r.w}W ${r.d}D ${r.l}L · ${r.gf}–${r.ga}</p>` : ""}
        <div class="label">Your changes</div>${planHtml(namedPlan())}${end}</div>
      <div class="plan-foot">${done ? `${next}<a class="btn ghost" href="${play}">See Year ${n} again</a>` : `<a class="btn primary" href="${play}">Carry on with Year ${n}</a>`}</div>`;
  } else {
    if (!$("sheethint")) $("bench").insertAdjacentHTML("afterend", `<p class="sheet-hint" id="sheethint"></p>`);
    sheetEditor($("pitch"), $("bench"), S, {
      hint: $("sheethint"), onMove: (man, to) => post("sheet", { man, to }), reset: S.sheet_chosen ? () => post("sheet", {}) : null,
    });
    planPanel($("deal"), S, S.plan, {
      tag: S.plan_chosen ? "your plan" : "automatic plan", onChange: (changes) => post("plan", { changes }),
      foot: `<a class="btn primary" href="${play}">Play Year ${n}</a>
        <button class="btn ghost" id="autoplan" ${S.plan_chosen ? "" : "disabled"}>Use the automatic plan</button>
        <p class="label">${AUTO_NOTE}</p>`,
    });
    $("autoplan").onclick = () => post("plan", { changes: null });
  }
  if ($("next")) $("next").onclick = () => postWindow(S.formation.code, [], false);
}

// --------------------------------------------------------------- talking to the server

async function call(path, body) {
  return api(`/api/dynasty/${S.state}/${path}`, { method: "POST", body: body ? JSON.stringify(body) : undefined });
}

async function move(kind, body) {
  if (busy || S.complete) return;
  busy = true;
  try {
    const s = await call(kind, body);
    justPicked = kind === "pick";
    // A dynasty drafted in this browser saves each season to the profile by itself (cup.js, C45).
    store.set(draftedKey(s.state), "1");
    setSession(s);
  } catch (e) {
    dropFlight();
    toast(e.status === 0 ? `${e.message}. Your dynasty is safe; try that again.` : e.message);
  } finally { busy = false; }
}

async function post(kind, body) {
  if (busy) return;
  busy = true;
  try { setSession(await call(kind, body), false); } catch (e) { toast(e.message); render(false); } finally { busy = false; }
}

async function postWindow(formation, releases, reshape) {
  if (busy) return;
  busy = true;
  try {
    setSession(await call("window", { formation, releases, reshape }));
    if (!reshape) scrollTo({ top: 0, behavior: "smooth" });
  } catch (e) { toast(e.message); } finally { busy = false; }
}

/* The seasons watched to the end, and how each went: asked with the state up to the last of
   them, so the reply holds no season that hasn't been seen. */
async function loadRecords() {
  const seen = D().seasons.filter((x) => x.complete && watched(x.state));
  if (!seen.length) return;
  const upTo = seen[seen.length - 1].state;
  try {
    const [r, legacy] = await Promise.all([api(`/api/dynasty/${upTo}/record`), api(`/api/dynasty/${upTo}/legacy`)]);
    const ok = new Set(seen.map((x) => x.number));
    RECORDS = Object.fromEntries(r.seasons.filter((x) => ok.has(x.number)).map((x) => [x.number, x]));
    LEGACY = legacy;
  } catch { /* the strip says "Not watched" */ }
}

/* The dynasty so far (C66), over the seasons watched to the end: its legends, its best
   eleven by match mark, and its top scorers. */
function renderLegacy() {
  const el = $("legacy");
  el.hidden = !LEGACY;
  if (!LEGACY) return;
  const d = D();
  const runs = Object.entries(d.runs).sort((a, b) => b[1] - a[1]);
  const c = runs.length && runs[0][1] < d.legend ? [...S.picks, ...S.waiting].find((x) => x.id === runs[0][0]) : null;
  el.innerHTML = `<h2 class="h2">Your dynasty so far</h2>
    <p class="sub">Over the ${LEGACY.seasons} season${LEGACY.seasons === 1 ? "" : "s"} you've watched to the end.</p>
    ${legacyHtml(LEGACY, "dynteam", c ? ` Longest run in your squad now: ${esc(c.name)}, ${runs[0][1]}.` : "")}`;
  legacyPitch(LEGACY, $("dynteam"));
}

(async function boot() {
  const meta = loadMeta().catch(() => {});
  if (!/^y[\w.~-]+$/.test(STATE_IN)) { location.replace("/start"); return; }
  try {
    S = await api(`/api/dynasty/${STATE_IN}`);
    await Promise.all([meta, loadRecords()]);
    setSession(S, false);
  } catch (e) {
    $("deal").innerHTML = `<div class="panel-h"><span class="label">Something went wrong</span></div><p class="dyn-intro">${esc(e.message)}</p>`;
  }
})();
