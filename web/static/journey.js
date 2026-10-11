"use strict";
/* The journey card: a side's whole tournament as one picture to keep or send (C27),
   after the cricket site's (its A80). Drawn on a canvas at 1080 px wide, so it is the
   same image on every screen, from the `journey` the tournament API already sent; no
   second request. The page also has the same numbers as a table (playersPanel), since
   a picture can't be read aloud. */

const JW = 1080, JPAD = 56;
const J_D = '"Unbounded"', J_S = '"Instrument Sans"';
const J_FONTS = [`800 80px ${J_D}`, `700 30px ${J_D}`, `600 20px ${J_S}`, `700 30px ${J_S}`];
const J_C = { bg: "#07080f", panel: "#11131f", panel2: "#171a29", line: "rgba(190,205,255,.12)", ink: "#eef1f8",
  ink2: "#aab1c6", ink3: "#7c839c", gold: "#f2c25a", gold2: "#ffe08e", ice: "#7cc4ff", win: "#5ad692", loss: "#ff6f6f",
  draw: "#5d6480", star: "#a998ff", pos: { GK: "#ffb35c", DF: "#6cb8ff", MF: "#a998ff", FW: "#ff7499" } };

function markColour(m) {
  if (m != null) m = Math.round(m * 10) / 10;            // the colour of the mark as shown, not of 5.95
  return m == null ? J_C.ink3 : m >= 8 ? J_C.gold : m >= 7 ? J_C.win : m >= 6 ? J_C.ink : J_C.loss;
}

/* What a player is remembered for, by his line. */
function roleLine(p) {
  const cs = `${p.clean_sheets} clean sheet${p.clean_sheets === 1 ? "" : "s"}`;
  const acc = p.accuracy == null ? "no passes" : `${p.accuracy}% passing`;
  if (p.pos === "GK") return `${p.saves} save${p.saves === 1 ? "" : "s"} · ${cs}`;
  if (p.pos === "DF") return `${acc} · ${cs}`;
  if (p.pos === "MF") return `${p.passes} passes · ${acc}`;
  return `${p.shots} shot${p.shots === 1 ? "" : "s"} · ${p.on_target} on target`;
}

function endingLine(j) {
  if (j.reached === "Champions" || j.reached === "Runners-up") return j.reached;
  return `Out in the ${j.reached.toLowerCase()}`;
}

function loadImage(url) {
  return new Promise((res) => {
    if (!url) return res(null);
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = () => res(null);
    im.src = url;
  });
}

/* Shrink a font until the text fits the width. */
function fitFont(ctx, text, weight, size, family, max) {
  let s = size;
  do { ctx.font = `${weight} ${s}px ${family}`; s -= 2; } while (ctx.measureText(text).width > max && s > 10);
}

function medallion(ctx, x, y, r, img, fill, text) {
  const g = ctx.createRadialGradient(x - r * 0.3, y - r * 0.4, r * 0.1, x, y, r);
  g.addColorStop(0, "#ffffff"); g.addColorStop(0.7, "#e7ecf6"); g.addColorStop(1, "#cfd7e8");
  ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fillStyle = fill || g; ctx.fill();
  if (img) {
    const s = r * 1.44, k = Math.min(s / img.width, s / img.height);
    ctx.drawImage(img, x - (img.width * k) / 2, y - (img.height * k) / 2, img.width * k, img.height * k);
  } else if (text) {
    ctx.fillStyle = "#1d1504"; ctx.font = `800 ${Math.round(r * 0.8)}px ${J_D}`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(text, x, y + r * 0.04); ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
  }
}

function roundRect(ctx, x, y, w, h, r, fill, stroke) {
  ctx.beginPath(); ctx.roundRect(x, y, w, h, r);
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 2; ctx.stroke(); }
}

/* side: {name, formation, avg, team, deep, ink, crest, human}; tag: "SEED 123" or "ROOM ABC123" */
async function drawJourneyCard(canvas, j, side, tag) {
  await Promise.all(J_FONTS.map((f) => document.fonts.load(f).catch(() => {})));
  const crests = await Promise.all(j.players.map((p) => loadImage(p.crest)));
  const awardImgs = await Promise.all(["top_scorer", "top_assists", "star"].map((k) => loadImage(j.awards[k]?.crest)));
  const sideImg = await loadImage(side.crest);
  const logoImg = await loadImage(SITE_LOGO);

  const ROW = 92, headH = 330, recordH = 190, tilesH = 210, awardsH = 230, xiH = 90 + ROW * j.players.length, footH = 110;
  const H = headH + recordH + tilesH + awardsH + xiH + footH;
  const dpr = 1;
  canvas.width = JW * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.fillStyle = J_C.bg; ctx.fillRect(0, 0, JW, H);

  // ---- header, in the side's colours, the centre circle drawn round the crest
  const cx0 = JW - JPAD - 90, cy0 = 150;
  const hg = ctx.createLinearGradient(0, 0, JW * 0.6, headH);
  hg.addColorStop(0, side.deep); hg.addColorStop(1, J_C.bg);
  ctx.fillStyle = hg; ctx.fillRect(0, 0, JW, headH);
  ctx.save(); ctx.beginPath(); ctx.rect(0, 0, JW, headH); ctx.clip();
  const glow = ctx.createRadialGradient(cx0, cy0, 10, cx0, cy0, 560);
  glow.addColorStop(0, side.team + "99"); glow.addColorStop(1, "transparent");
  ctx.fillStyle = glow; ctx.fillRect(0, 0, JW, headH);
  ctx.lineWidth = 2;
  [[128, ".14"], [220, ".08"], [330, ".05"]].forEach(([r, a]) => {
    ctx.strokeStyle = `rgba(255,255,255,${a})`; ctx.beginPath(); ctx.arc(cx0, cy0, r, 0, Math.PI * 2); ctx.stroke();
  });
  ctx.restore();
  const bar = ctx.createLinearGradient(0, 0, JW, 0);
  bar.addColorStop(0, side.team); bar.addColorStop(1, side.team + "00");
  ctx.fillStyle = bar; ctx.fillRect(0, 0, JW, 6);

  medallion(ctx, cx0, cy0, 90, sideImg, sideImg ? null : side.team,
            sideImg ? null : side.human ? side.name[0].toUpperCase() : "✦");
  ctx.fillStyle = side.ink || J_C.ice; ctx.font = `650 19px ${J_S}`;
  ctx.fillText(`${tag} · TOURNAMENT JOURNEY`.split("").join(String.fromCharCode(8202)), JPAD, 76);
  ctx.fillStyle = "#fff"; fitFont(ctx, side.name, 800, 72, J_D, JW - JPAD * 2 - 240);
  ctx.fillText(side.name, JPAD, 168);
  ctx.fillStyle = J_C.ink2; ctx.font = `600 25px ${J_S}`;
  ctx.fillText(`${side.formation} · average rating ${side.avg}`, JPAD, 214);
  const champ = j.reached === "Champions";
  const ending = (champ ? "🏆 " : "") + endingLine(j);
  if (champ) { ctx.shadowColor = "rgba(242,194,90,.7)"; ctx.shadowBlur = 30; }
  ctx.fillStyle = champ ? J_C.gold2 : j.reached === "Runners-up" ? J_C.ink : J_C.ink2;
  fitFont(ctx, ending, 800, 40, J_D, JW - JPAD * 2 - 240);
  ctx.fillText(ending, JPAD, 292);
  ctx.shadowBlur = 0;

  // ---- record and form
  let y = headH + 30;
  const [w, d, l] = j.record;
  ctx.fillStyle = J_C.ink; ctx.font = `800 80px ${J_D}`;
  const rec = `${w}-${d}-${l}`;
  ctx.fillText(rec, JPAD, y + 88);
  const recW = ctx.measureText(rec).width;
  ctx.fillStyle = J_C.ink3; ctx.font = `650 17px ${J_S}`;
  ctx.fillText("WON · DRAWN · LOST", JPAD, y + 128);
  const fx = JPAD + Math.max(recW, 230) + 50;
  ctx.fillText(`FORM · GOALS ${j.goals_for}–${j.goals_against}`, fx, y + 30);
  j.matches.forEach((m, i) => {
    const cx = fx + 22 + i * 54, cy = y + 80;
    ctx.beginPath(); ctx.arc(cx, cy, 19, 0, Math.PI * 2);
    ctx.fillStyle = m.outcome === "w" ? J_C.win : m.outcome === "l" ? J_C.loss : J_C.draw; ctx.fill();
    if (m.knockout) { ctx.lineWidth = 3; ctx.strokeStyle = J_C.ice; ctx.beginPath(); ctx.arc(cx, cy, 25, 0, Math.PI * 2); ctx.stroke(); }
    ctx.fillStyle = "#07080f"; ctx.font = `800 15px ${J_D}`; ctx.textAlign = "center";
    ctx.fillText(m.outcome.toUpperCase(), cx, cy + 6); ctx.textAlign = "left";
  });
  if (j.matches.some((m) => m.knockout)) {
    ctx.fillStyle = J_C.ink3; ctx.font = `650 15px ${J_S}`;
    ctx.fillText("BLUE RING = KNOCKOUT", fx, y + 140);
  }

  // ---- stat tiles
  y = headH + recordH;
  const tiles = [
    [j.goals_for, "GOALS"], [j.possession == null ? "–" : `${j.possession}%`, "POSSESSION"],
    [`${j.shots}/${j.on_target}`, "SHOTS / ON TARGET"], [j.accuracy == null ? "–" : `${j.accuracy}%`, "PASS ACCURACY"],
    [j.clean_sheets, "CLEAN SHEETS"], [j.matches.length, "MATCHES"],
  ];
  const tw = (JW - JPAD * 2 - 20 * 2) / 3;
  tiles.forEach(([v, label], i) => {
    const tx = JPAD + (i % 3) * (tw + 20), ty = y + Math.floor(i / 3) * 96;
    roundRect(ctx, tx, ty, tw, 80, 18, J_C.panel, J_C.line);
    // Value over label: Unbounded is wide, and side by side "131/55" ran into its label.
    ctx.fillStyle = J_C.ink; fitFont(ctx, String(v), 700, 28, J_D, tw - 44); ctx.fillText(String(v), tx + 22, ty + 42);
    ctx.fillStyle = J_C.ink3; ctx.font = `650 13px ${J_S}`; ctx.fillText(label, tx + 22, ty + 66);
  });

  // ---- awards
  y += tilesH;
  const awards = [["TOP SCORER", j.awards.top_scorer, (a) => `${a.n} goal${a.n === 1 ? "" : "s"}`, J_C.gold],
    ["MOST ASSISTS", j.awards.top_assists, (a) => `${a.n} assist${a.n === 1 ? "" : "s"}`, J_C.win],
    ["PLAYER OF THE TOURNAMENT", j.awards.star, (a) => `${a.n.toFixed(2)} average mark`, J_C.star]];
  const aw = (JW - JPAD * 2 - 40) / 3;
  awards.forEach(([title, a, val, colour], i) => {
    const ax = JPAD + i * (aw + 20), ay = y;
    roundRect(ctx, ax, ay, aw, 200, 20, J_C.panel2, J_C.line);
    ctx.save(); ctx.beginPath(); ctx.roundRect(ax, ay, aw, 200, 20); ctx.clip();
    ctx.fillStyle = colour; ctx.fillRect(ax, ay, aw, 4);
    if (awardImgs[i]) { ctx.globalAlpha = 0.08; const s = 190; ctx.drawImage(awardImgs[i], ax + aw - s * 0.75, ay + 20, s, s); ctx.globalAlpha = 1; }
    ctx.restore();
    ctx.fillStyle = colour; ctx.font = `650 14px ${J_S}`; ctx.fillText(title, ax + 22, ay + 42);
    if (!a) { ctx.fillStyle = J_C.ink3; ctx.font = `700 26px ${J_S}`; ctx.fillText("Nobody", ax + 22, ay + 110); return; }
    ctx.fillStyle = J_C.ink; fitFont(ctx, a.name, 700, 30, J_S, aw - 44); ctx.fillText(a.name, ax + 22, ay + 100);
    ctx.fillStyle = J_C.ink3; ctx.font = `600 16px ${J_S}`; ctx.fillText(`${a.short} ${a.season.slice(2)}`, ax + 22, ay + 130);
    ctx.fillStyle = colour; fitFont(ctx, val(a), 700, 24, J_D, aw - 44); ctx.fillText(val(a), ax + 22, ay + 176);
  });

  // ---- the eleven
  y += awardsH;
  ctx.fillStyle = J_C.gold; ctx.font = `650 17px ${J_S}`; ctx.fillText("THE ELEVEN", JPAD, y + 30);
  ctx.fillStyle = J_C.ink3; ctx.textAlign = "right"; ctx.fillText("AVERAGE MARK /10", JW - JPAD, y + 30); ctx.textAlign = "left";
  y += 56;
  j.players.forEach((p, i) => {
    const ry = y + i * ROW;
    if (i % 2 === 0) roundRect(ctx, JPAD - 14, ry - 6, JW - JPAD * 2 + 28, ROW - 6, 16, "rgba(255,255,255,.025)");
    medallion(ctx, JPAD + 30, ry + ROW / 2 - 4, 30, crests[i]);
    const nx = JPAD + 80, pc = J_C.pos[p.pos];
    roundRect(ctx, nx, ry + 14, 46, 26, 7, pc + "26", pc + "66");
    ctx.fillStyle = pc; ctx.font = `700 14px ${J_S}`; ctx.textAlign = "center"; ctx.fillText(p.pos, nx + 23, ry + 32); ctx.textAlign = "left";
    ctx.fillStyle = J_C.ink; fitFont(ctx, p.name, 700, 28, J_S, 470); ctx.fillText(p.name, nx + 58, ry + 37);
    ctx.fillStyle = J_C.ink3; ctx.font = `600 16px ${J_S}`;
    ctx.fillText(`${p.short} ${p.season.slice(2)} · ${p.rating}`, nx + 58, ry + 66);
    const parts = [`${p.apps} apps`];
    if (p.goals) parts.push(`${p.goals} G`);
    if (p.assists) parts.push(`${p.assists} A`);
    const fxp = JPAD + 640;
    ctx.fillStyle = J_C.ink; ctx.font = `700 22px ${J_S}`; ctx.fillText(parts.join(" · "), fxp, ry + 37);
    ctx.fillStyle = J_C.ink2; ctx.font = `600 16px ${J_S}`; ctx.fillText(roleLine(p), fxp, ry + 66);
    ctx.fillStyle = markColour(p.mark); ctx.font = `800 32px ${J_D}`; ctx.textAlign = "right";
    ctx.fillText(p.mark == null ? "–" : p.mark.toFixed(1), JW - JPAD, ry + 54); ctx.textAlign = "left";
  });

  // ---- footer: the logo itself
  y = H - footH;
  ctx.fillStyle = J_C.line; ctx.fillRect(JPAD, y + 10, JW - JPAD * 2, 2);
  if (logoImg) {
    const lh = 44, lw = (logoImg.width / logoImg.height) * lh;
    ctx.drawImage(logoImg, JPAD, y + 40, lw, lh);
  } else {
    ctx.fillStyle = J_C.ink; ctx.font = `800 32px ${J_D}`; ctx.fillText(SITE_NAME, JPAD, y + 72);
  }
  ctx.fillStyle = J_C.ink3; ctx.font = `600 16px ${J_S}`; ctx.textAlign = "right";
  ctx.fillText("MARKS ARE THIS GAME'S OWN · uclnights11.vercel.app", JW - JPAD, y + 68); ctx.textAlign = "left";
}

/* The overlay that shows the card, with Download and (on a phone) Share. */
async function openJourney(j, side, tag) {
  closeJourney();
  const box = document.createElement("div");
  box.className = "modal journey-modal"; box.id = "journeymodal";
  box.innerHTML = `<div class="journey-frame" role="dialog" aria-modal="true" aria-label="Journey card">
    <div class="journey-actions"><button class="btn primary small" id="jdown" disabled>Download</button>
      <button class="btn ghost small" id="jshare" hidden>Share</button>
      <button class="btn ghost small" id="jclose">Close</button></div>
    <div class="journey-scroll"><canvas id="journeycanvas" role="img"
      aria-label="${esc(side.name)}: ${esc(j.reached)}, ${j.record.join("-")} won-drawn-lost"></canvas></div></div>`;
  document.body.append(box);
  $("jclose").onclick = closeJourney;
  box.onclick = (e) => { if (e.target === box) closeJourney(); };
  box.onkeydown = (e) => { if (e.key === "Escape") closeJourney(); };
  $("jclose").focus();
  const canvas = $("journeycanvas");
  await drawJourneyCard(canvas, j, side, tag);
  const blob = await new Promise((r) => canvas.toBlob(r, "image/png"));
  if (!blob || !$("journeymodal")) return;
  const name = `uclnights11-journey-${side.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.png`;
  const url = URL.createObjectURL(blob);
  $("jdown").disabled = false;
  $("jdown").onclick = () => { const a = document.createElement("a"); a.href = url; a.download = name; a.click(); };
  const file = new File([blob], name, { type: "image/png" });
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    $("jshare").hidden = false;
    $("jshare").onclick = () => navigator.share({ files: [file], title: `${side.name} · UCLnights11` }).catch(() => {});
  }
}

function closeJourney() { const m = $("journeymodal"); if (m) m.remove(); }

/* The same numbers as a table on the page. */
function playersPanel(j) {
  return `<section class="panel"><div class="panel-h"><span class="label">Your players</span><span class="label">mark /10, this game's own</span></div>
    <div class="table-scroll"><table class="players-table"><thead><tr><th>Player</th><th title="Average match mark">Mark</th><th title="Appearances">Apps</th><th title="Goals">G</th><th title="Assists">A</th>
      <th title="Shots (on target)">Shots</th><th title="Pass accuracy">Pass</th></tr></thead><tbody>
    ${j.players.map((p) => `<tr><td><div class="t">${crest(p.crest, 22, p.club)}<span class="pos ${p.pos}">${p.pos}</span>
        <div><b>${esc(p.name)}</b><small>${esc(roleLine(p))}</small></div></div></td>
      <td><b class="mark" style="color:${markColour(p.mark)}">${p.mark == null ? "–" : p.mark.toFixed(1)}</b></td><td>${p.apps}</td><td>${p.goals || ""}</td><td>${p.assists || ""}</td><td>${p.shots}<small>${p.on_target}</small></td>
      <td>${p.accuracy == null ? "–" : `${p.accuracy}%`}</td></tr>`).join("")}
    </tbody></table></div></section>`;
}
