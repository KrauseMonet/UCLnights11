"use strict";
/* The completed draft: /squad#STATE for a solo draft, /squad?room=CODE for a room's, shown
   between the last pick (and the plan) and kick-off. A side's ratings line by line, each
   set against the deck's own club-seasons at their best (game.squad_ratings), the eleven
   on its pitch, the bench and its plan; in a room, every seat's side side by side. The
   draft is over by now, so nothing is hidden: Memory mode is about drafting blind. */

const SQ_ROOM = new URLSearchParams(location.search).get("room");
shell(SQ_ROOM ? "friends" : "draft");
const SQ_STATE = location.hash.slice(1);
let SQ = null, PICK = 0;

// [key, label, the colour of its meter]. The keeper and the bench have no "line" colour of
// their own in a form a meter needs, so they borrow the position chips' (--gk) and ice.
const TILES = [
  ["overall", "Overall", "var(--ice)"], ["attack", "Attack", "var(--fw)"], ["midfield", "Midfield", "var(--mf)"],
  ["defence", "Defence", "var(--df)"], ["goalkeeper", "Goalkeeper", "var(--gk)"], ["bench", "Bench", "var(--ice-2)"],
];
const COLS = [["overall", "OVR"], ["attack", "ATT"], ["midfield", "MID"], ["defence", "DEF"], ["goalkeeper", "GK"], ["bench", "BEN"]];
const whole = (v) => v == null ? "–" : Math.round(v);
const sideName = (s) => s.you ? "Your XI" : s.name;
const cupUrl = () => SQ_ROOM ? `/cup?room=${esc(SQ.room.code)}` : `/cup#${esc(SQ_STATE)}`;

function heroHtml() {
  const s = SQ.sides[PICK];
  const where = SQ_ROOM ? `Room ${esc(SQ.room.code)} · ${esc(SQ.room.format)} · ` : "";
  const many = SQ.sides.length > 1;
  return `<div class="kicker">${where}Draft complete</div>
    <h1 class="arch-h">${many ? "The <em>squads</em>" : "Your <em>squad</em>"}</h1>
    <p class="sub">${many ? `Every friend's side, rated line by line.` : `Your ${esc(s.formation)}, rated line by line.`}
      Each figure is set against the deck's ${SQ.field} club-seasons at their best eleven. Ratings are this game's
      judgement, not data (<a href="/about">how</a>).</p>
    <div class="cup-actions sq-acts">${actionsHtml()}</div>`;
}

function actionsHtml() {
  // A new plan is a new tournament, so it is offered only before a match has been seen (C41).
  const seen = +(store.get(`cup:${SQ_STATE}`) || 0) > 0;
  const plan = !SQ_ROOM && SQ.sides[0].bench.length && !seen ? `<a class="btn ghost" href="/draft#${esc(SQ_STATE)}">Change your team or plan</a>` : "";
  return `<a class="btn primary" href="${cupUrl()}">${SQ_ROOM ? "To the tournament" : "Kick off"}</a>${plan}
    <button class="btn ghost" id="copy">Copy link</button>`;
}

/* A room's sides in one table, each column's best marked; a row picks the side shown below. */
function compareHtml() {
  if (SQ.sides.length < 2) return "";
  const cols = COLS.filter(([k]) => SQ.sides.some((s) => s.ratings[k] != null));
  const best = Object.fromEntries(cols.map(([k]) => [k, Math.max(...SQ.sides.map((s) => s.ratings[k] ?? -1))]));
  return `<section class="panel sq-compare"><div class="panel-h"><span class="label">Side by side</span><span class="label">tap a side to see it</span></div>
    <div class="sq-scroll"><table class="sq-table"><thead><tr><th>Side</th>${cols.map(([k, l]) => `<th title="${k}">${l}</th>`).join("")}</tr></thead>
    <tbody>${SQ.sides.map((s, i) => `<tr class="${s.you ? "you" : ""} ${i === PICK ? "on" : ""}">
      <td><button class="sq-pick" data-i="${i}" aria-pressed="${i === PICK}">${sideCrest(s, 28)}<span><b class="${s.you ? "you-name" : ""}">${esc(sideName(s))}</b><small>${esc(s.you ? `${s.name} · ` : "")}${esc(s.formation)}</small></span></button></td>
      ${cols.map(([k]) => `<td class="${s.ratings[k] != null && s.ratings[k] === best[k] ? "best" : ""}">${whole(s.ratings[k])}</td>`).join("")}</tr>`).join("")}
    </tbody></table></div></section>`;
}

/* What each man of a side cost, in an auction room (C72): person id -> €m. */
function priceOf(s) {
  return s.auction ? Object.fromEntries(s.auction.buys.map((b) => [b.card.id, b.price])) : {};
}

/* The room's auction (C72): its biggest buys and its bargains, each with who bought him. */
function auctionHtml() {
  const A = SQ.auction;
  if (!A) return "";
  const row = (b) => `<li>${crest(b.card.crest, 28, b.card.club)}<div class="who"><b>${esc(b.card.name)}</b>
      <small>${esc(b.username)} · ${esc(b.card.short)} ${esc(b.card.season.slice(2))} · ${b.card.rating}${b.beat ? ` · beat ${b.beat} bid${b.beat === 1 ? "" : "s"}` : ""}</small></div>
      <span class="auc-price">€${b.price}m</span></li>`;
  const list = (rows, empty) => rows.length ? `<ol class="sq-auc">${rows.map(row).join("")}</ol>` : `<p class="empty">${empty}</p>`;
  return `<section class="cup-grid sq-auction">
    <div class="cup-stack"><section class="panel an-board"><div class="panel-h"><span class="label">Biggest buys</span><span class="label">${A.kind === "sealed" ? "sealed bids" : "open auction"} · €${A.budget}m each</span></div>
      ${list(A.biggest, "Nothing was sold.")}</section></div>
    <div class="cup-stack"><section class="panel an-board"><div class="panel-h"><span class="label">Bargains</span><span class="label">€${A.bargain}m or less, best first</span></div>
      ${list(A.bargains, `Nobody went for €${A.bargain}m or less.`)}</section></div></section>`;
}

// The share of the deck's club-seasons a figure is strictly above, in words.
const standing = (p) => p >= 100 ? "above every side in the deck" : p <= 0 ? "the lowest in the deck" : `above ${p}% of the deck`;

function tileHtml(s, [k, label, colour]) {
  const v = s.ratings[k], p = s.better_than[k];
  if (v == null) return k === "bench" ? "" : `<div class="sq-tile"><span class="label">${label}</span><b>–</b></div>`;
  const gold = k === "overall" && s.you;
  return `<div class="sq-tile ${k}" style="--m:${gold ? "var(--trophy)" : colour}">
    <span class="label">${label}</span><b class="${gold ? "gold" : ""}">${whole(v)}</b>
    <div class="sq-meter" role="img" aria-label="Rated above ${p}% of the deck's club-seasons"><i style="width:${p}%"></i></div>
    <small>${standing(p)}</small></div>`;
}

/* The eleven by line, back to front, each line with its average; the side's best player and
   its weakest are marked, since that is what a team sheet is read for. */
function linesHtml(s) {
  const order = ["GK", "DF", "MF", "FW"];
  const paid = priceOf(s);
  const top = Math.max(...s.xi.map((c) => c.rating)), low = Math.min(...s.xi.map((c) => c.rating));
  const key = { GK: "goalkeeper", DF: "defence", MF: "midfield", FW: "attack" };
  return order.map((line) => {
    const men = s.xi.filter((c) => c.pos === line);
    if (!men.length) return "";
    return `<div class="sq-line"><div class="sq-line-h"><span class="label">${LINES[line]}</span><span class="label">average <b>${whole(s.ratings[key[line]])}</b></span></div>
      ${men.map((c) => `<div class="sq-man">${posChip(c.slot)}${crest(c.crest, 28, c.club)}
        <div class="who"><b>${esc(c.name)}</b><small>${esc(c.club)} ${esc(c.season)}</small></div>
        ${c.rating === top ? `<span class="sq-flag top">best</span>` : c.rating === low && top !== low ? `<span class="sq-flag low">weakest</span>` : ""}
        ${paid[c.id] == null ? "" : `<span class="auc-price">€${paid[c.id]}m</span>`}${rate(c.rating)}</div>`).join("")}</div>`;
  }).join("");
}

function detailHtml(s) {
  const r = s.ratings;
  return `<section class="sq-side">
    <div class="sq-side-h">${sideCrest(s, 48)}<div><b class="${s.you ? "you-name" : ""}">${esc(sideName(s))}</b>
      <small>${esc(s.formation)} · ${s.clubs} club${s.clubs === 1 ? "" : "s"}${s.you && SQ_ROOM ? ` · ${esc(s.name)}` : ""}</small></div></div>
    <div class="sq-tiles">${TILES.map((t) => tileHtml(s, t)).join("")}</div>
    ${s.auction ? `<p class="sq-engine">At the auction ${s.you ? "you" : "they"} spent <b>€${s.auction.spent}m</b> of €${SQ.auction.budget}m, with €${s.auction.left}m left over${s.auction.buys.length ? `; the dearest was ${esc(s.auction.buys[0].card.name)} at €${s.auction.buys[0].price}m` : ""}.</p>` : ""}
    <p class="sq-engine">What decides a match is the engine's own mix: <b>attack ${r.engine_attack.toFixed(1)}</b>
      (${standing(s.better_than.engine_attack)}) and <b>defence ${r.engine_defence.toFixed(1)}</b>
      (${standing(s.better_than.engine_defence)}). The midfield counts towards both and the keeper most of all towards defence.</p>
    <div class="cup-grid">
      <div class="cup-stack"><section class="panel"><div class="panel-h"><span class="label">By line</span><span class="label">${esc(s.formation)}</span></div>
        <div class="sq-lines">${linesHtml(s)}</div></section></div>
      <div class="cup-stack"><section class="panel"><div class="panel-h"><span class="label">${s.you ? "Your XI" : "Their XI"}</span><span class="label">${esc(s.formation)}</span></div>
        <div class="pitch" id="sqpitch" ${s.you && !SQ_ROOM ? "data-xi" : ""}></div><div class="bench-row" id="sqbench" hidden></div>
        ${s.bench.length ? `<div class="plan-box"><div class="panel-h"><span class="label">${s.you ? "Your" : "Their"} changes</span></div>${planHtml(s.plan)}</div>` : ""}</section></div>
    </div></section>`;
}

function render() {
  const s = SQ.sides[PICK];
  $("hero").innerHTML = heroHtml();
  $("compare").innerHTML = compareHtml() + auctionHtml();
  $("detail").innerHTML = detailHtml(s);
  renderPitch($("sqpitch"), s.slots, s.xi, null);
  renderBench($("sqbench"), s.bench, s.bench.length);
  $("copy").onclick = () => copyText(location.href, "Link copied");
  $("compare").querySelectorAll(".sq-pick").forEach((b) => b.onclick = () => {
    PICK = +b.dataset.i;
    render();
    $("detail").scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

(async function boot() {
  loadMeta().catch(() => {});
  const bad = SQ_ROOM ? !/^[A-Za-z0-9]{6}$/.test(SQ_ROOM) : !/^[\w.-]+$/.test(SQ_STATE);
  if (bad) { location.href = SQ_ROOM ? "/friends" : "/start"; return; }
  // Handed over by the draft page when it sent us here: drawn without waiting (C57).
  const ready = SQ_ROOM ? null : handoff.take(`squad:${SQ_STATE}`);
  try { SQ = ready || await api(SQ_ROOM ? `/api/rooms/${SQ_ROOM}/squads` : `/api/draft/${SQ_STATE}/squad`); }
  catch (e) {
    $("hero").innerHTML = `<div class="kicker">Draft complete</div><h1 class="arch-h">Not here</h1><p class="sub">${esc(e.message)}</p>
      <div class="cup-actions sq-acts"><a class="btn primary" href="${SQ_ROOM ? `/room#${esc(SQ_ROOM)}` : `/draft#${esc(SQ_STATE)}`}">Back to the draft</a></div>`;
    return;
  }
  if (SQ_ROOM) store.set(`squad:${SQ.room.code}`, "1");
  render();
})();
