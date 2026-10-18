"use strict";
/* The end of a dynasty (C76): /legacy#DYNASTY. Every season side by side, the dynasty's
   records and the men who made it, read off the tournaments already played
   (game.dynasty_review). Asked with the state up to the last season watched to the end in
   this browser, as the dynasty page asks for its record, so nothing here is a season not
   yet seen. A link from elsewhere, with no season of it watched here, shows every finished
   season, as a solo link shows its whole tournament. Charts are inline SVG in the analysis
   page's colours (common.js), and each carries its numbers as labels or a table. */

shell("draft");
const LG_FULL = location.hash.slice(1);
let RV = null;

// How far a season went, shallowest first: the ladder's rungs.
const DEPTH = ["League phase", "Knockout play-offs", "Round of 16", "Quarter-finals", "Semi-finals", "Runners-up", "Champions"];
const RUNG = { "League phase": "League", "Knockout play-offs": "Play-offs", "Round of 16": "Last 16",
  "Quarter-finals": "Quarters", "Semi-finals": "Semis", "Runners-up": "Final", Champions: "Won it" };
const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"];
const word = (n) => WORDS[n] ?? String(n);
const cap = (s) => s[0].toUpperCase() + s.slice(1);
const plural = (n, w, ws = `${w}s`) => `${n} ${n === 1 ? w : ws}`;
const sideTag = (s) => s.you ? "Your XI" : `${s.club} ${s.season.slice(2)}`;
const years = (ns) => ns.length > 1 ? `${ns.slice(0, -1).map((n) => `Year ${n}`).join(", ")} and Year ${ns[ns.length - 1]}` : `Year ${ns[0]}`;
const ordinal = (n) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th"}`;
const seasonLink = (n) => `/cup?season=${n}#${LG_FULL}`;

/* The seasons this browser has watched to the end, from the first: the state up to the
   last of them, or the whole state if it has watched none. */
function watchedUpTo(full) {
  const blocks = full.split("~");
  let k = 0;
  while (k < blocks.length && store.get(`dyndone:${blocks.slice(0, k + 1).join("~")}`) === "1") k++;
  return k ? blocks.slice(0, k).join("~") : full;
}

function section(n, title, sub, body) {
  return `<section class="an-sec" id="lg-${n}"><div class="an-sec-h"><span class="an-n">${n}</span><h2>${title}</h2></div>
    ${sub ? `<p class="sub">${sub}</p>` : ""}${body}</section>`;
}

// ---------------------------------------------------------------- hero

function heroHtml() {
  const t = RV.totals, S = RV.seasons, n = t.seasons;
  const where = n === RV.length ? "the end" : n > RV.length ? `${n} seasons` : `${n} season${n === 1 ? "" : "s"} so far`;
  const won = S.filter((s) => s.reached === "Champions").map((s) => s.number);
  const lost = S.filter((s) => s.reached === "Runners-up").map((s) => s.number);
  const best = S.find((s) => s.number === RV.best);
  const said = [
    won.length ? `Champions in ${years(won)}.` : `Your best: ${best.reached.toLowerCase()} in Year ${best.number}.`,
    lost.length ? `Beaten in the final in ${years(lost)}.` : "",
    `${t.players} men from ${t.clubs} clubs wore your colours`,
  ].filter(Boolean).join(" ");
  const legends = RV.legacy.legends.length;
  const places = S.filter((s) => s.position).map((s) => s.position);
  const tiles = [
    [t.titles, t.titles === 1 ? "Title" : "Titles"],
    [t.finals, "Finals reached"],
    [t.matches, `Matches · ${t.w}W ${t.d}D ${t.l}L`],
    [`${t.gf}–${t.ga}`, "Goals for and against"],
    [places.length ? fmt1(places.reduce((a, b) => a + b, 0) / places.length) : "–", "Average league-phase place"],
    [legends, legends === 1 ? "Legend" : "Legends"],
  ];
  return `<div class="kicker">Dynasty · seed ${esc(RV.seed)} · ${where}</div>
    <h1 class="arch-h">${cap(word(n))} season${n === 1 ? "" : "s"}, <em>${word(t.titles)} title${t.titles === 1 ? "" : "s"}</em></h1>
    <p class="sub">${esc(said)}${legends ? `, and ${word(legends)} of them became ${legends === 1 ? "a legend" : "legends"}.` : "."}
      Every number is read off the tournaments you watched; ratings, marks and match statistics are this game's design (<a href="/faq#stats">why</a>).</p>
    <div class="an-tiles">${tiles.map(([v, l]) => `<div class="an-tile"><b>${v}</b><span>${esc(l)}</span></div>`).join("")}</div>
    <div class="cup-actions an-back"><a class="btn primary small" href="/dynasty#${esc(LG_FULL)}">Back to your dynasty</a>
      <button class="btn ghost small" id="lgcopy">Copy link</button></div>`;
}

// ---------------------------------------------------------------- season by season

/* How far each season went, as a column up a ladder of rounds: gold for a title. */
// The paired charts are drawn PAIR wide, so their labels read at half a page's width.
const PAIR = 460;

function ladderSvg(S) {
  const W = PAIR, H = 280, padL = 66, padB = 30, padT = 22, inner = W - padL - 10;
  const rungs = DEPTH.length, y = (k) => padT + (H - padT - padB) * (1 - k / rungs);
  const band = inner / S.length, barW = Math.min(30, band - 8);
  let out = "";
  DEPTH.forEach((st, k) => {
    out += `<line x1="${padL}" x2="${W - 10}" y1="${y(k + 1)}" y2="${y(k + 1)}" stroke="${AC.grid}" stroke-width="1"/>
      <text x="${padL - 8}" y="${y(k + 1) + 4}" text-anchor="end" class="an-axis">${RUNG[st]}</text>`;
  });
  S.forEach((s, i) => {
    const k = DEPTH.indexOf(s.reached) + 1, x = padL + band * i + (band - barW) / 2, top = y(k), h = y(0) - top, r = Math.min(4, h);
    const colour = s.reached === "Champions" ? AC.you : AC.other;
    out += `<g class="an-bar"><title>Year ${s.number}: ${esc(s.reached)}</title>
      <path d="M${x},${y(0)} V${top + r} Q${x},${top} ${x + r},${top} H${x + barW - r} Q${x + barW},${top} ${x + barW},${top + r} V${y(0)} Z" fill="${colour}"/>
      <text x="${x + barW / 2}" y="${H - 10}" text-anchor="middle" class="an-axis">Y${s.number}</text></g>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" class="an-svg" role="img" aria-label="How far each season went">${out}</svg>`;
}

/* A line through one value a season, each point labelled. ``invert`` puts the lowest value
   at the top (a league place); ``bands`` shade ranges of the scale with a name. */
function lineSvg(S, values, o) {
  const W = PAIR, H = o.height || 260, padL = 34, padR = o.bands ? 64 : 12, padB = 30, padT = 22;
  const inner = W - padL - padR, band = inner / S.length;
  const t = (v) => (v - o.min) / (o.max - o.min);
  const y = (v) => padT + (H - padT - padB) * (o.invert ? t(v) : 1 - t(v));
  const x = (i) => padL + band * i + band / 2;
  let out = "";
  for (const [lo, hi, name, fill] of o.bands || []) {
    out += `<rect x="${padL}" y="${Math.min(y(lo), y(hi))}" width="${inner}" height="${Math.abs(y(hi) - y(lo))}" fill="${fill}"/>
      <text x="${W - padR + 8}" y="${(y(lo) + y(hi)) / 2 + 4}" class="an-axis">${name}</text>`;
  }
  for (const v of o.ticks) {
    out += `<line x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}" stroke="${AC.grid}" stroke-width="1"/>
      <text x="${padL - 8}" y="${y(v) + 4}" text-anchor="end" class="an-axis">${v}</text>`;
  }
  const pts = S.map((s, i) => values[i] == null ? null : [x(i), y(values[i])]);
  const path = pts.filter(Boolean).map(([px, py], k) => `${k ? "L" : "M"}${px},${py}`).join(" ");
  out += `<path d="${path}" fill="none" stroke="${o.colour}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
  S.forEach((s, i) => {
    if (!pts[i]) return;
    const [px, py] = pts[i], label = o.fmt(values[i]);
    out += `<g class="an-bar"><title>Year ${s.number}: ${esc(o.name)} ${label}</title>
      <circle cx="${px}" cy="${py}" r="4.5" fill="${o.colour}" stroke="#11131f" stroke-width="2"/>
      <text x="${px}" y="${py - 10}" text-anchor="middle" class="an-val-lab">${label}</text></g>
      <text x="${px}" y="${H - 10}" text-anchor="middle" class="an-axis">Y${s.number}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" class="an-svg" role="img" aria-label="${esc(o.name)} by season">${out}</svg>`;
}

function seasonsHtml() {
  const S = RV.seasons;
  const rows = S.map((s) => {
    // Who put you out, and who won it when that was someone else.
    const won = s.champion.you ? "" : s.out_by && s.out_by.key === s.champion.key ? "went on to win it" : `${sideTag(s.champion)} won it`;
    const out = s.champion.you ? "<b class=\"lg-you\">You won it</b>"
      : `<div class="t">${s.out_by ? sideCrest(s.out_by, 22) : ""}<span class="nm">${s.out_by ? esc(sideTag(s.out_by)) : "In the league phase"}
        <small>${esc(won)}</small></span></div>`;
    const man = (p, v) => p ? `<span class="lg-man">${esc(p.name)} <small>${v}</small></span>` : "–";
    return `<tr class="${s.reached === "Champions" ? "you" : ""}">
      <td><a href="${seasonLink(s.number)}">Year ${s.number}</a></td><td>${esc(s.formation)}</td>
      <td>${s.position ?? "–"}</td><td>${s.points}</td><td>${s.w}–${s.d}–${s.l}</td><td>${s.gf}–${s.ga}</td>
      <td class="reach">${esc(s.reached)}</td><td class="lg-out">${out}</td>
      <td>${s.ratings.overall.toFixed(1)}</td>
      <td>${man(s.top_scorer, s.top_scorer && plural(s.top_scorer.goals, "goal"))}</td>
      <td>${man(s.star, s.star && s.star.mark != null ? s.star.mark.toFixed(2) : "")}</td></tr>`;
  }).join("");
  const places = S.map((s) => s.position);
  const zones = [[0.5, 8.5, "Last 16", "rgba(124,196,255,.07)"], [8.5, 24.5, "Play-offs", "rgba(255,255,255,.03)"],
    [24.5, 36.5, "Out", "rgba(0,0,0,0)"]];
  const best = S.find((s) => s.number === RV.best), worst = S.find((s) => s.number === RV.worst);
  const sub = S.length > 1
    ? `The best was Year ${best.number} (${best.reached.toLowerCase()}, ${best.points} points in the league phase); the worst Year ${worst.number} (${worst.reached.toLowerCase()}). Open a year to see it again.`
    : "";
  return section("01", "Season by season", sub, `<div class="lg-pair">
      <div class="panel an-panel"><div class="panel-h lg-ph"><span class="label">How far each season went</span></div>
        ${legend([[AC.you, "Champions"], [AC.other, "Every other season"]])}${ladderSvg(S)}</div>
      <div class="panel an-panel"><div class="panel-h lg-ph"><span class="label">League-phase place, of 36</span></div>
        ${lineSvg(S, places, { name: "League-phase place", min: 0.5, max: 36.5, invert: true, ticks: [1, 8, 16, 24, 36],
          bands: zones, colour: AC.other, fmt: (v) => v, height: 270 })}</div></div>
    <div class="panel an-panel lg-table"><div class="table-scroll"><table class="an-table">
      <thead><tr><th>Year</th><th>Shape</th><th title="League-phase place">Place</th><th title="League-phase points">Pts</th><th>W–D–L</th><th>Goals</th>
        <th>Reached</th><th class="lg-out">Put out by</th><th title="The eleven's average rating">Rating</th><th>Top scorer</th><th title="The best average mark">Star</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`);
}

// ---------------------------------------------------------------- the squad through the years

/* Two stacked series a season: men kept from last season (blue) under men new to the squad (gold). */
function turnoverSvg(S) {
  const W = PAIR, H = 260, padL = 34, padB = 30, padT = 22, inner = W - padL - 10;
  const top = Math.max(...S.map((s) => (s.kept || 0) + s.signed));
  const y = (v) => padT + (H - padT - padB) * (1 - v / top);
  const band = inner / S.length, barW = Math.min(30, band - 8);
  let out = "";
  for (let v = 0; v <= top; v += 7) {
    out += `<line x1="${padL}" x2="${W - 10}" y1="${y(v)}" y2="${y(v)}" stroke="${AC.grid}" stroke-width="1"/>
      <text x="${padL - 8}" y="${y(v) + 4}" text-anchor="end" class="an-axis">${v}</text>`;
  }
  S.forEach((s, i) => {
    const x = padL + band * i + (band - barW) / 2, kept = s.kept || 0;
    const seg = (from, n, colour, what) => n ? `<rect x="${x}" y="${y(from + n)}" width="${barW}" height="${y(from) - y(from + n) - 1}" rx="3" fill="${colour}"><title>Year ${s.number}: ${n} ${what}</title></rect>
      <text x="${x + barW / 2}" y="${(y(from) + y(from + n)) / 2 + 4}" text-anchor="middle" class="lg-seg">${n}</text>` : "";
    out += `<g>${seg(0, kept, AC.other, "kept from last season")}${seg(kept, s.signed, AC.you, "new to the squad")}
      <text x="${x + barW / 2}" y="${H - 10}" text-anchor="middle" class="an-axis">Y${s.number}</text></g>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" class="an-svg" role="img" aria-label="Men kept and men new to the squad by season">${out}</svg>`;
}

function squadHtml() {
  const S = RV.seasons;
  const vals = S.map((s) => s.ratings.overall);
  const lo = Math.floor(Math.min(...vals)) - 1, hi = Math.ceil(Math.max(...vals)) + 1;
  const ticks = Array.from({ length: hi - lo + 1 }, (_, k) => lo + k).filter((v, k, a) => a.length <= 7 || k % 2 === 0);
  const f = (v) => v == null ? "–" : v.toFixed(1);
  const rows = S.map((s) => `<tr><td><a href="${seasonLink(s.number)}">Year ${s.number}</a></td><td><b>${f(s.ratings.overall)}</b></td>
    <td>${f(s.ratings.attack)}</td><td>${f(s.ratings.midfield)}</td><td>${f(s.ratings.defence)}</td><td>${f(s.ratings.goalkeeper)}</td>
    <td>${f(s.ratings.bench)}</td><td>${s.better_than == null ? "–" : `${s.better_than}%`}</td>
    <td>${s.kept ?? "–"}</td><td>${s.number === 1 ? "–" : s.released}</td><td>${s.number === 1 ? "–" : s.left}</td><td>${s.signed}</td><td>${s.originals}</td></tr>`).join("");
  const first = S[0], last = S[S.length - 1];
  const released = S.reduce((a, s) => a + s.released, 0), left = S.reduce((a, s) => a + s.left, 0);
  const sub = S.length > 1
    ? `The eleven's average rating went from ${f(first.ratings.overall)} to ${f(last.ratings.overall)}. You released ${plural(released, "man", "men")};
      ${plural(left, "man", "men")} left because the deck had no season for them or no place in your shape.
      Of your first ${first.signed}, ${last.originals} ${last.originals === 1 ? "was" : "were"} still there in Year ${last.number}.`
    : "";
  return section("02", "The squad through the years", sub, `<div class="lg-pair">
      <div class="panel an-panel"><div class="panel-h lg-ph"><span class="label">The eleven's average rating</span></div>
        ${lineSvg(S, vals, { name: "Average rating", min: lo, max: hi, ticks, colour: AC.you, fmt: (v) => v.toFixed(1) })}</div>
      <div class="panel an-panel"><div class="panel-h lg-ph"><span class="label">Who was in the squad</span></div>
        ${legend([[AC.other, "Kept from last season"], [AC.you, "New to the squad"]])}${turnoverSvg(S)}</div></div>
    <div class="panel an-panel lg-table"><div class="table-scroll"><table class="an-table">
      <thead><tr><th>Year</th><th>Eleven</th><th>Attack</th><th>Midfield</th><th>Defence</th><th>Keeper</th><th>Bench</th>
        <th title="The share of the deck's club-seasons, at their best eleven, that your eleven rates above">Above</th>
        <th>Kept</th><th>Released</th><th>Left</th><th>New</th><th title="Men of Year 1's squad still in it">From Year 1</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
      <p class="an-note lg-note">Averages of declared ratings, each man counted in the line of the place he stood (the squad page's figures). "Above" sets the eleven against every club-season in the deck at its best eleven.</p></div>`);
}

// ---------------------------------------------------------------- goals

function goalsHtml() {
  const S = RV.seasons;
  const most = S.reduce((a, s) => s.gf > a.gf ? s : a), tight = S.reduce((a, s) => s.ga < a.ga ? s : a);
  const sub = `Most scored: Year ${most.number}, ${most.gf} in ${most.w + most.d + most.l} matches. Fewest conceded: Year ${tight.number}, ${tight.ga}.
    ${plural(RV.totals.clean_sheets, "clean sheet")} in all.`;
  return section("03", "Goals, season by season", sub, `<div class="panel an-panel">
    ${legend([[AC.you, "Scored"], [AC.other, "Conceded"]])}
    ${columnsSvg(S.map((s) => `Y${s.number}`), [{ name: "scored", values: S.map((s) => s.gf), colour: AC.you },
      { name: "conceded", values: S.map((s) => s.ga), colour: AC.other }], "Goals scored and conceded by season")}</div>`);
}

// ---------------------------------------------------------------- records

function matchCard(title, m, accent) {
  if (!m) return `<div class="an-honour" style="--accent:${accent}"><span class="label">${title}</span><b class="nobody">None</b></div>`;
  const extra = m.pens ? ` · ${m.pens[0]}–${m.pens[1]} on penalties` : m.extra_time ? " · after extra time" : "";
  return `<div class="an-honour" style="--accent:${accent}"><span class="label">${title}</span>
    <div class="an-score"><span>${sideCrest(m.home, 28)}<em>${esc(sideTag(m.home))}</em></span><b>${m.hg}–${m.ag}</b>
      <span>${sideCrest(m.away, 28)}<em>${esc(sideTag(m.away))}</em></span></div>
    <small class="an-where"><a href="${seasonLink(m.season)}">Year ${m.season}</a> · ${esc(m.stage === "League phase" ? m.label : `${m.stage} · ${m.label}`)}${extra}</small></div>`;
}

function seasonCard(title, n, accent) {
  const s = RV.seasons.find((x) => x.number === n);
  return `<div class="an-honour" style="--accent:${accent}"><span class="label">${title}</span>
    <div class="an-val"><a href="${seasonLink(n)}">Year ${n}</a> · ${esc(s.reached)}</div>
    <small class="lg-small">${s.w}W ${s.d}D ${s.l}L · ${s.gf}–${s.ga}${s.position ? ` · ${ordinal(s.position)} in the league phase` : ""} · ${esc(s.formation)}</small></div>`;
}

function runCard(title, r, accent) {
  if (!r) return `<div class="an-honour" style="--accent:${accent}"><span class="label">${title}</span><b class="nobody">None</b></div>`;
  const at = (m) => `Year ${m.season}, ${m.stage === "League phase" ? m.label.toLowerCase() : `${m.stage.toLowerCase()} ${m.label.toLowerCase()}`}`;
  return `<div class="an-honour" style="--accent:${accent}"><span class="label">${title}</span>
    <div class="an-val">${plural(r.length, "match", "matches")}</div>
    <small class="lg-small">${r.length === 1 ? esc(at(r.first)) : `From ${esc(at(r.first))} to ${esc(at(r.last))}`}</small></div>`;
}

function clubCard(title, o, accent) {
  if (!o) return `<div class="an-honour" style="--accent:${accent}"><span class="label">${title}</span><b class="nobody">Nobody</b></div>`;
  return `<div class="an-honour" style="--accent:${accent}"><span class="label">${title}</span>
    <div class="an-who">${sideCrest(o, 36)}<div><b>${esc(o.club)}</b><small>${plural(o.p, "match", "matches")} · ${o.gf}–${o.ga}</small></div></div>
    <div class="an-val">${o.w}W ${o.d}D ${o.l}L</div></div>`;
}

// Two records naming one match: the most goals is often the biggest win, so it isn't shown twice.
const same = (a, b) => a && b && a.season === b.season && a.stage === b.stage && a.label === b.label;

function recordsHtml() {
  const r = RV.records;
  return section("04", "Records", `Across all ${plural(RV.totals.matches, "match", "matches")} against ${RV.totals.met} clubs. A shoot-out counts as a draw, so it never ends a run unbeaten.`,
    `<div class="an-honours">
      ${seasonCard("Best season", RV.best, AC.you)}
      ${RV.seasons.length > 1 ? seasonCard("Worst season", RV.worst, AC.mid) : ""}
      ${matchCard("Biggest win", r.biggest_win, AC.you)}
      ${matchCard("Heaviest defeat", r.heaviest_defeat, AC.other)}
      ${same(r.most_goals, r.biggest_win) || same(r.most_goals, r.heaviest_defeat) ? "" : matchCard("Most goals in a match", r.most_goals, AC.mid)}
      ${runCard("Longest unbeaten run", r.unbeaten, AC.you)}
      ${runCard("Longest winning run", r.winning, AC.you)}
      ${clubCard("Your nemesis", r.nemesis, AC.other)}
      ${clubCard("Your favourite opponent", r.favourite, AC.you)}</div>`);
}

// ---------------------------------------------------------------- the men

function award(title, row, value, accent) {
  if (!row) return `<div class="an-honour" style="--accent:${accent}"><span class="label">${title}</span><b class="nobody">Nobody</b></div>`;
  return `<div class="an-honour" style="--accent:${accent}"><span class="label">${title}</span>
    <div class="an-who">${crest(row.crest, 36, row.name)}<div><b>${esc(row.name)}</b><small>${plural(row.seasons, "season")} · ${plural(row.apps, "app")}</small></div></div>
    <div class="an-val">${value}</div></div>`;
}

const BOARDS = [["apps", "Appearances", (v) => v], ["assists", "Assists", (v) => v],
  ["mark", "Average mark", (v) => v.toFixed(2)], ["clean_sheets", "Clean sheets", (v) => v], ["seasons", "Seasons played", (v) => v]];

function menHtml() {
  const b = RV.boards, top = (k) => b[k][0];
  const awards = `<div class="an-honours">
    ${award("Player of the dynasty", top("mark"), top("mark") && `${top("mark").value.toFixed(2)} average mark`, "#a998ff")}
    ${award("Golden boot", top("goals"), top("goals") && plural(top("goals").value, "goal"), AC.you)}
    ${award("Most assists", top("assists"), top("assists") && plural(top("assists").value, "assist"), AC.other)}
    ${award("Most appearances", top("apps"), top("apps") && plural(top("apps").value, "match", "matches"), AC.mid)}
    ${award("Golden glove", top("clean_sheets"), top("clean_sheets") && plural(top("clean_sheets").value, "clean sheet"), "#5ad692")}
    ${award("Longest serving", top("seasons"), top("seasons") && `${plural(top("seasons").value, "season")} played`, AC.mid)}</div>`;
  const boards = BOARDS.map(([k, title, f]) => {
    const rows = b[k], lead = rows.length ? rows[0].value : 1;
    const note = k === "mark" ? `<small class="an-note">${RV.min_apps}+ matches</small>` : k === "clean_sheets" ? `<small class="an-note">keepers</small>` : "";
    return `<div class="panel an-board"><div class="panel-h"><span class="label">${title}</span>${note}</div>
      ${rows.length ? `<ol>${rows.map((r) => `<li>${crest(r.crest, 22, r.name)}
        <div class="who"><b>${esc(r.name)}</b><small>${plural(r.apps, "app")} · ${plural(r.seasons, "season")} · ${esc(r.club)} ${esc(r.season)}</small>
        <div class="an-lead"><i style="width:${(r.value / lead) * 100}%"></i></div></div><span class="n">${f(r.value)}</span></li>`).join("")}</ol>`
        : `<p class="empty">Nobody.</p>`}</div>`;
  }).join("");
  return section("05", "The men who made it", "Over every match they played for you. A man's club and season are his latest with you.",
    `${awards}<div class="dyn-legacy lg-legacy">${legacyHtml(RV.legacy, "lgteam")}</div><div class="an-boards lg-boards">${boards}</div>`);
}

// ---------------------------------------------------------------- where they came from

function clubsHtml() {
  const t = RV.totals, rows = RV.clubs, lead = rows.length ? rows[0].men : 1;
  return section("06", "Where they came from", `${t.players} men from ${t.clubs} clubs, each counted once, at the club he first joined you from.`,
    `<div class="panel an-board lg-clubs"><ol>${rows.map((c) => `<li>${crest(c.crest, 22, c.club)}
      <div class="who"><b>${esc(c.club)}</b><div class="an-lead"><i style="width:${(c.men / lead) * 100}%"></i></div></div>
      <span class="n">${c.men}</span></li>`).join("")}</ol></div>`);
}

// ---------------------------------------------------------------- boot

function render() {
  $("lghero").innerHTML = heroHtml();
  $("lgbody").innerHTML = [seasonsHtml(), squadHtml(), goalsHtml(), recordsHtml(), menHtml(), clubsHtml()].join("");
  legacyPitch(RV.legacy, $("lgteam"));
  $("lgcopy").onclick = () => copyText(location.href, "Link copied");
}

(async function boot() {
  if (!/^y[\w.~-]+$/.test(LG_FULL)) { location.replace("/start"); return; }
  try {
    RV = await api(`/api/dynasty/${watchedUpTo(LG_FULL)}/review`);
  } catch (e) {
    $("lghero").innerHTML = `<div class="kicker">Dynasty</div><h1 class="arch-h">Not yet</h1>
      <p class="sub">${esc(e.status === 409 ? "No season of this dynasty has been played yet." : e.message)}</p>
      <div class="cup-actions an-back"><a class="btn ghost small" href="/dynasty#${esc(LG_FULL)}">Back to the dynasty</a></div>`;
    return;
  }
  render();
})();
