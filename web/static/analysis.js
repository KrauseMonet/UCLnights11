"use strict";
/* The tournament analysis (C28): /analysis#STATE for a solo tournament,
   /analysis?room=CODE for a room's. Every chart is inline SVG built here, with no
   library, as on the cricket site (its A104). Colours were run through the dataviz
   validator against the panel colour: gold #c08a1e and blue #4a86d8 for two series,
   with a neutral grey as the midpoint (a draw) or the field's average. Every chart
   carries its numbers as labels or a table, so nothing is told by colour alone. */

const AN_ROOM = new URLSearchParams(location.search).get("room");
shell(AN_ROOM ? "friends" : "draft");
const AN_STATE = location.hash.slice(1);
const AC = { you: "#c08a1e", other: "#4a86d8", mid: "#56637f", grid: "rgba(255,255,255,.08)", ink2: "#aebedb", ink3: "#6c7fa3" };
let AN = null, YOU = null, SCOPE = "all";

const fmt1 = (v) => v == null ? "–" : v.toFixed(1);       // a rate: always one decimal, so 3.0 sits under 3.3
const pctOr = (v) => v == null ? "–" : `${v}%`;
const sideTag = (s) => s.you ? "Your XI" : s.human ? s.club : `${s.club} ${s.season.slice(2)}`;

// ---------------------------------------------------------------- hero and honours

function heroHtml() {
  const h = AN.hero;
  const where = AN_ROOM ? `Room ${esc(AN_ROOM.toUpperCase())}` : `Seed ${esc(AN_STATE.split("-")[0])}`;
  const tiles = [
    [h.matches, "Matches"], [h.goals, `Goals · ${fmt1(h.goals_per_match)} a match`],
    [h.shots.toLocaleString(), `Shots · ${pctOr(h.on_target_share)} on target`],
    [pctOr(h.conversion), "Shots scored"], [pctOr(h.accuracy), "Pass accuracy"],
    [`${h.extra_time} / ${h.shootouts}`, "Extra time / shoot-outs"],
  ];
  return `<div class="kicker">${where} · Tournament analysis</div>
    <h1 class="arch-h">How the <em>nights</em> played</h1>
    <p class="sub">Every match of the tournament, read off the engine's own numbers. Shots, possession, passing and marks
      are this game's design, not real data (<a href="/faq#stats">why</a>).</p>
    <div class="an-tiles">${tiles.map(([v, l]) => `<div class="an-tile"><b>${v}</b><span>${esc(l)}</span></div>`).join("")}</div>
    <div class="cup-actions an-back"><a class="btn ghost small" href="${AN_ROOM ? `/cup?room=${esc(AN_ROOM)}` : `/cup#${esc(AN_STATE)}`}">Back to the tournament</a></div>`;
}

function honour(title, row, value, accent) {
  if (!row) return `<div class="an-honour" style="--accent:${accent}"><span class="label">${title}</span><b class="nobody">Nobody</b></div>`;
  return `<div class="an-honour" style="--accent:${accent}"><span class="label">${title}</span>
    <div class="an-who">${crest(row.crest, 36, row.name)}<div><b>${esc(row.name)}</b><small>${esc(sideTag(row.side))}</small></div></div>
    <div class="an-val">${value}</div></div>`;
}

function matchBrief(title, f) {
  if (!f) return "";
  const where = f.stage === "Group stage" ? `Group ${f.group} · ${f.label}` : `${f.stage} · ${f.label}`;
  return `<div class="an-honour" style="--accent:${AC.mid}"><span class="label">${title}</span>
    <div class="an-score"><span>${sideCrest(f.home, 28)}<em>${esc(sideTag(f.home))}</em></span><b>${f.hg}–${f.ag}</b>
      <span>${sideCrest(f.away, 28)}<em>${esc(sideTag(f.away))}</em></span></div><small class="an-where">${esc(where)}</small></div>`;
}

function honoursHtml() {
  const b = AN.boards, top = (k) => b[k][0];
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  return section("01", "Honours", "", `<div class="an-honours">
    ${honour("Golden boot", top("goals"), top("goals") && plural(top("goals").value, "goal"), AC.you)}
    ${honour("Most assists", top("assists"), top("assists") && plural(top("assists").value, "assist"), AC.other)}
    ${honour("Player of the tournament", top("mark"), top("mark") && `${top("mark").value.toFixed(2)} average mark`, "#c77dff")}
    ${honour("Golden glove", top("clean_sheets"), top("clean_sheets") && plural(top("clean_sheets").value, "clean sheet"), "#3ddc97")}
    ${matchBrief("Biggest win", AN.biggest_win)}
    ${matchBrief("Most goals in a match", AN.most_goals)}</div>`);
}

function section(n, title, sub, body, extra = "") {
  return `<section class="an-sec" id="an-${n}"><div class="an-sec-h"><span class="an-n">${n}</span><h2>${title}</h2>${extra}</div>
    ${sub ? `<p class="sub">${sub}</p>` : ""}${body}</section>`;
}

// ---------------------------------------------------------------- when the goals came

/* Columns from one baseline, 4px rounded tops, value on each cap. One or two series. */
function columnsSvg(labels, series) {
  const W = 720, H = 260, padL = 34, padB = 34, padT = 26, inner = W - padL - 10;
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const step = max <= 5 ? 1 : max <= 12 ? 2 : max <= 30 ? 5 : max <= 60 ? 10 : 20;
  const top = Math.ceil(max / step) * step;
  const y = (v) => padT + (H - padT - padB) * (1 - v / top);
  const band = inner / labels.length, barW = Math.min(24, (band - 16) / series.length);
  let out = "";
  for (let v = 0; v <= top; v += step) {
    out += `<line x1="${padL}" x2="${W - 10}" y1="${y(v)}" y2="${y(v)}" stroke="${AC.grid}" stroke-width="1"/>
      <text x="${padL - 8}" y="${y(v) + 4}" text-anchor="end" class="an-axis">${v}</text>`;
  }
  labels.forEach((lab, i) => {
    const cx = padL + band * i + band / 2, groupW = barW * series.length + 2 * (series.length - 1);
    series.forEach((s, k) => {
      const v = s.values[i], x = cx - groupW / 2 + k * (barW + 2), yy = y(v), h = y(0) - yy;
      const r = Math.min(4, h);
      const path = h > 0 ? `M${x},${y(0)} V${yy + r} Q${x},${yy} ${x + r},${yy} H${x + barW - r} Q${x + barW},${yy} ${x + barW},${yy + r} V${y(0)} Z` : "";
      out += `<g class="an-bar"><title>${esc(lab)}: ${v} ${esc(s.name)}</title>
        <rect x="${x - 4}" y="${padT}" width="${barW + 8}" height="${H - padT - padB}" fill="transparent"/>
        ${path ? `<path d="${path}" fill="${s.colour}"/>` : ""}
        <text x="${x + barW / 2}" y="${yy - 6}" text-anchor="middle" class="an-val-lab">${v}</text></g>`;
    });
    out += `<text x="${cx}" y="${H - 10}" text-anchor="middle" class="an-axis">${esc(lab)}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" class="an-svg" role="img" aria-label="${esc(series.map((s) => s.name).join(" and "))} by minute">${out}</svg>`;
}

function legend(items) {
  return `<div class="an-legend">${items.map(([c, l]) => `<span><i style="background:${c}"></i>${esc(l)}</span>`).join("")}</div>`;
}

function minutesHtml() {
  const mine = AN.your_minutes;
  const scope = mine ? `<div class="chips an-scope" role="radiogroup" aria-label="Whose goals">
      <button class="chip" role="radio" aria-checked="${SCOPE === "all"}" data-scope="all">Whole tournament</button>
      <button class="chip" role="radio" aria-checked="${SCOPE === "you"}" data-scope="you">Your side</button></div>` : "";
  const labels = AN.buckets;
  let chart;
  if (SCOPE === "you" && mine) {
    chart = legend([[AC.you, "Scored"], [AC.other, "Conceded"]]) + columnsSvg(labels, [
      { name: "scored", values: mine.scored, colour: AC.you }, { name: "conceded", values: mine.conceded, colour: AC.other }]);
  } else {
    chart = columnsSvg(labels, [{ name: "goals", values: AN.goal_minutes, colour: AC.you }]);
  }
  const late = AN.goal_minutes.slice(4, 6).reduce((a, b) => a + b, 0), all = AN.goal_minutes.reduce((a, b) => a + b, 0);
  const sub = all ? `${Math.round((late / all) * 100)}% of the goals came in the last half hour of normal time.` : "";
  return section("02", "When the goals came", sub, `<div class="panel an-panel" id="minutes">${chart}</div>`, scope);
}

// ---------------------------------------------------------------- your side against the field

function compareHtml() {
  if (!AN.you) return "";
  const rows = [["goals", "Goals a match", fmt1], ["conceded", "Conceded a match", fmt1], ["shots", "Shots a match", fmt1],
    ["on_target", "On target a match", fmt1], ["possession", "Possession", pctOr], ["accuracy", "Pass accuracy", pctOr]];
  const body = rows.map(([k, label, f]) => {
    const a = AN.you[k], b = AN.average[k], max = Math.max(a || 0, b || 0, 0.01);
    const bar = (v, c, who) => `<div class="an-hbar"><i style="width:${v == null ? 0 : (v / max) * 100}%;background:${c}" title="${who}: ${f(v)}"></i><b>${f(v)}</b></div>`;
    return `<div class="an-cmp"><span class="an-cmp-l">${label}</span>${bar(a, AC.you, sideTag(YOU || { you: true }))}${bar(b, AC.mid, "Tournament average")}</div>`;
  }).join("");
  const you = YOU ? sideTag(YOU) : "Your side";
  return section("03", `${esc(you)} against the field`, "Per match, beside the average of every side in the tournament.",
    `<div class="panel an-panel">${legend([[AC.you, you], [AC.mid, "Tournament average"]])}<div class="an-cmps">${body}</div></div>`);
}

// ---------------------------------------------------------------- home and away, round by round

function homeHtml() {
  const h = AN.home, n = h.home_win + h.draw + h.away_win;
  if (!n) return "";
  const parts = [["Home wins", h.home_win, AC.you], ["Draws", h.draw, AC.mid], ["Away wins", h.away_win, AC.other]];
  const bar = parts.map(([l, v, c]) => v ? `<i style="flex:${v};background:${c}" title="${l}: ${v} (${Math.round((v / n) * 100)}%)"></i>` : "").join("");
  const labels = parts.map(([l, v, c]) => `<span><i style="background:${c}"></i>${l} <b>${v}</b> <small>${Math.round((v / n) * 100)}%</small></span>`).join("");
  return section("04", "Home and away", `${n} matches with a home side (the final is on neutral ground).`,
    `<div class="panel an-panel"><div class="an-split">${bar}</div><div class="an-legend an-split-l">${labels}</div></div>`);
}

function stagesHtml() {
  const rows = AN.stages.map((s) => `<tr><td>${esc(s.stage)}</td><td>${s.matches}</td><td>${s.goals}</td><td>${fmt1(s.goals_per_match)}</td>
    <td>${fmt1(s.shots_per_match)}</td><td>${s.extra_time}</td><td>${s.shootouts}</td></tr>`).join("");
  return section("05", "Round by round", "", `<div class="panel an-panel"><div class="table-scroll"><table class="an-table">
    <thead><tr><th>Round</th><th>Matches</th><th>Goals</th><th>A match</th><th title="Per side, per match">Shots</th><th>Extra time</th><th>Shoot-outs</th></tr></thead>
    <tbody>${rows}</tbody></table></div></div>`);
}

// ---------------------------------------------------------------- every side

const SIDE_COLS = [
  ["name", "Side"], ["reached", "Reached"], ["p", "P"], ["w", "W"], ["d", "D"], ["l", "L"], ["gd", "GD"],
  ["possession", "Poss"], ["shots", "Shots"], ["accuracy", "Pass"], ["clean_sheets", "CS"], ["mark", "Mark"],
];
let SIDE_SORT = null;

function sidesHtml() {
  const rows = AN.sides.map((s, i) => ({ ...s, gd: s.gf - s.ga, order: i }));
  if (SIDE_SORT) {
    const [k, dir] = SIDE_SORT;
    rows.sort((a, b) => k === "name" ? dir * sideTag(a).localeCompare(sideTag(b))
      : k === "reached" ? dir * (a.order - b.order) : dir * ((b[k] ?? -1) - (a[k] ?? -1)) || a.order - b.order);
  }
  const head = SIDE_COLS.map(([k, l]) => `<th><button class="an-sort" data-k="${k}" aria-label="Sort by ${l}">${l}${SIDE_SORT && SIDE_SORT[0] === k ? (SIDE_SORT[1] > 0 ? " ▾" : " ▴") : ""}</button></th>`).join("");
  const body = rows.map((s) => `<tr class="${s.you ? "you" : s.human ? "friend" : ""}">
    <td><div class="t">${sideCrest(s, 22)}<span class="nm">${esc(sideTag(s))}</span></div></td><td class="reach">${esc(s.reached)}</td>
    <td>${s.p}</td><td>${s.w}</td><td>${s.d}</td><td>${s.l}</td><td>${s.gd > 0 ? "+" : ""}${s.gd}</td>
    <td>${pctOr(s.possession)}</td><td>${fmt1(s.shots)}</td><td>${pctOr(s.accuracy)}</td><td>${s.clean_sheets}</td><td>${s.mark == null ? "–" : s.mark.toFixed(2)}</td></tr>`).join("");
  return section("06", "Every side", "Furthest first. Tap a heading to sort. Shots are per match; mark is the eleven's average.",
    `<div class="panel an-panel"><div class="table-scroll"><table class="an-table an-sides"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div></div>`);
}

// ---------------------------------------------------------------- players

const BOARDS = [
  ["goals", "Goals", (v) => v], ["assists", "Assists", (v) => v], ["on_target", "Shots on target", (v) => v],
  ["mark", "Average mark", (v) => v.toFixed(2)], ["accuracy", "Pass accuracy", (v) => `${v}%`],
  ["saves", "Saves", (v) => v], ["clean_sheets", "Clean sheets", (v) => v],
];

function boardsHtml() {
  const boards = BOARDS.map(([k, title, f]) => {
    const rows = AN.boards[k];
    const lead = rows.length ? rows[0].value : 1;
    const note = k === "mark" || k === "accuracy" ? `<small class="an-note">${AN.min_apps}+ matches${k === "accuracy" ? ", outfield" : ""}</small>` : "";
    return `<div class="panel an-board"><div class="panel-h"><span class="label">${title}</span>${note}</div>
      ${rows.length ? `<ol>${rows.map((r) => `<li class="${r.side.you ? "you" : ""}">${crest(r.crest, 22, r.name)}
        <div class="who"><b>${esc(r.name)}</b><small>${esc(sideTag(r.side))} · ${r.apps} app${r.apps === 1 ? "" : "s"}</small>
        <div class="an-lead"><i style="width:${(r.value / lead) * 100}%"></i></div></div><span class="n">${f(r.value)}</span></li>`).join("")}</ol>`
        : `<p class="empty">Nobody yet.</p>`}</div>`;
  }).join("");
  return section("07", "The players", "One row per player per side: the same man in two drawn club-seasons is two rows.",
    `<div class="an-boards">${boards}</div>`);
}

// ---------------------------------------------------------------- boot

function render() {
  $("anhero").innerHTML = heroHtml();
  $("anbody").innerHTML = [honoursHtml(), minutesHtml(), compareHtml(), homeHtml(), stagesHtml(), sidesHtml(), boardsHtml()].join("");
  $("anbody").querySelectorAll("[data-scope]").forEach((b) => b.onclick = () => {
    SCOPE = b.dataset.scope;
    render();
  });
  $("anbody").querySelectorAll(".an-sort").forEach((b) => b.onclick = () => {
    const k = b.dataset.k;
    SIDE_SORT = SIDE_SORT && SIDE_SORT[0] === k ? [k, -SIDE_SORT[1]] : [k, 1];
    render();
    $("an-06").scrollIntoView({ block: "start" });
  });
}

(async function boot() {
  const bad = AN_ROOM ? !/^[A-Za-z0-9]{6}$/.test(AN_ROOM) : !/^[\w.-]+$/.test(AN_STATE);
  if (bad) { location.href = AN_ROOM ? "/friends" : "/draft"; return; }
  try {
    const r = await api(AN_ROOM ? `/api/rooms/${AN_ROOM}/analysis` : `/api/tournament/${AN_STATE}/analysis`);
    AN = r.analysis; YOU = r.you;
  } catch (e) {
    $("anhero").innerHTML = `<div class="kicker">Tournament analysis</div><h1 class="arch-h">Not here</h1><p class="sub">${esc(e.message)}</p>`;
    return;
  }
  render();
})();
