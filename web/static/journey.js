"use strict";
/* The journey card: a side's whole tournament as one picture to keep or send (C27),
   after the cricket site's (its A80). Drawn on a canvas at 1080 px wide, so it is the
   same image on every screen, from the `journey` the tournament API already sent; no
   second request. The page also has the same numbers as a table (playersPanel), since
   a picture can't be read aloud. */

const JW = 1080, JPAD = 56;
const J_FONTS = ['400 80px "Anton"', '700 30px "Archivo"', '600 20px "JetBrains Mono"', '800 30px "Archivo"'];
const J_C = { bg: "#050b1c", panel: "#0c1a36", panel2: "#112446", line: "rgba(255,255,255,.10)", ink: "#f3f6fb",
  ink2: "#aebedb", ink3: "#6c7fa3", gold: "#f5b83d", gold2: "#ffd873", mint: "#3ddc97", red: "#ff6a4d",
  pos: { GK: "#f5b83d", DF: "#5aa9ff", MF: "#3ddc97", FW: "#ff7a59" } };

function markColour(m) {
  if (m != null) m = Math.round(m * 10) / 10;            // the colour of the mark as shown, not of 5.95
  return m == null ? J_C.ink3 : m >= 8 ? J_C.gold : m >= 7 ? J_C.mint : m >= 6 ? J_C.ink : J_C.red;
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
  if (j.reached === "Champions") return "CHAMPIONS";
  if (j.reached === "Runners-up") return "RUNNERS-UP";
  return `OUT IN THE ${j.reached.toUpperCase()}`;
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
    ctx.fillStyle = "#1a1204"; ctx.font = `400 ${Math.round(r)}px "Anton"`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
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

  const ROW = 92, headH = 330, recordH = 190, tilesH = 210, awardsH = 230, xiH = 90 + ROW * j.players.length, footH = 110;
  const H = headH + recordH + tilesH + awardsH + xiH + footH;
  const dpr = 1;
  canvas.width = JW * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.fillStyle = J_C.bg; ctx.fillRect(0, 0, JW, H);

  // ---- header, in the side's colours
  const hg = ctx.createLinearGradient(0, 0, JW, headH);
  hg.addColorStop(0, side.deep); hg.addColorStop(1, J_C.bg);
  ctx.fillStyle = hg; ctx.fillRect(0, 0, JW, headH);
  ctx.save(); ctx.beginPath(); ctx.rect(0, 0, JW, headH); ctx.clip();
  ctx.strokeStyle = "rgba(255,255,255,.035)"; ctx.lineWidth = 2;
  for (let x = -headH; x < JW + headH; x += 16) { ctx.beginPath(); ctx.moveTo(x, headH); ctx.lineTo(x + headH * 0.47, 0); ctx.stroke(); }
  const glow = ctx.createRadialGradient(0, headH * 1.2, 10, 0, headH * 1.2, 520);
  glow.addColorStop(0, side.team + "aa"); glow.addColorStop(1, "transparent");
  ctx.fillStyle = glow; ctx.fillRect(0, 0, JW, headH);
  ctx.restore();
  ctx.fillStyle = side.team; ctx.fillRect(0, 0, JW, 8);

  medallion(ctx, JW - JPAD - 90, 150, 90, sideImg, sideImg ? null : side.team,
            sideImg ? null : side.human ? side.name[0].toUpperCase() : "✦");
  ctx.fillStyle = J_C.gold; ctx.font = '600 20px "JetBrains Mono"';
  ctx.fillText(`${tag} · TOURNAMENT JOURNEY`.split("").join(String.fromCharCode(8202)), JPAD, 76);
  ctx.fillStyle = "#fff"; fitFont(ctx, side.name.toUpperCase(), 400, 96, '"Anton"', JW - JPAD * 2 - 220);
  ctx.fillText(side.name.toUpperCase(), JPAD, 178);
  ctx.fillStyle = J_C.ink2; ctx.font = '700 26px "Archivo"';
  ctx.fillText(`${side.formation} · average rating ${side.avg}`, JPAD, 222);
  const champ = j.reached === "Champions";
  ctx.font = '400 54px "Anton"';
  if (champ) { ctx.shadowColor = "rgba(245,184,61,.7)"; ctx.shadowBlur = 30; }
  ctx.fillStyle = champ ? J_C.gold2 : j.reached === "Runners-up" ? J_C.ink : J_C.ink2;
  ctx.fillText((champ ? "🏆 " : "") + endingLine(j), JPAD, 296);
  ctx.shadowBlur = 0;

  // ---- record and form
  let y = headH + 30;
  const [w, d, l] = j.record;
  ctx.fillStyle = J_C.ink; ctx.font = '400 92px "Anton"';
  const rec = `${w}-${d}-${l}`;
  ctx.fillText(rec, JPAD, y + 92);
  const recW = ctx.measureText(rec).width;
  ctx.fillStyle = J_C.ink3; ctx.font = '600 18px "JetBrains Mono"';
  ctx.fillText("WON · DRAWN · LOST", JPAD, y + 130);
  const fx = JPAD + Math.max(recW, 230) + 50;
  ctx.fillText(`FORM · GOALS ${j.goals_for}–${j.goals_against}`, fx, y + 30);
  j.matches.forEach((m, i) => {
    const cx = fx + 22 + i * 54, cy = y + 80;
    ctx.beginPath(); ctx.arc(cx, cy, 19, 0, Math.PI * 2);
    ctx.fillStyle = m.outcome === "w" ? J_C.mint : m.outcome === "l" ? J_C.red : "#4b5a78"; ctx.fill();
    if (m.knockout) { ctx.lineWidth = 4; ctx.strokeStyle = J_C.gold; ctx.beginPath(); ctx.arc(cx, cy, 25, 0, Math.PI * 2); ctx.stroke(); }
    ctx.fillStyle = "#08132b"; ctx.font = '800 18px "Archivo"'; ctx.textAlign = "center";
    ctx.fillText(m.outcome.toUpperCase(), cx, cy + 6); ctx.textAlign = "left";
  });
  if (j.matches.some((m) => m.knockout)) {
    ctx.fillStyle = J_C.ink3; ctx.font = '600 16px "JetBrains Mono"';
    ctx.fillText("GOLD RING = KNOCKOUT", fx, y + 140);
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
    roundRect(ctx, tx, ty, tw, 80, 16, J_C.panel, J_C.line);
    ctx.fillStyle = J_C.ink; ctx.font = '400 40px "Anton"'; ctx.fillText(String(v), tx + 22, ty + 52);
    ctx.fillStyle = J_C.ink3; ctx.font = '600 15px "JetBrains Mono"';
    ctx.textAlign = "right"; ctx.fillText(label, tx + tw - 20, ty + 50); ctx.textAlign = "left";
  });

  // ---- awards
  y += tilesH;
  const awards = [["TOP SCORER", j.awards.top_scorer, (a) => `${a.n} goal${a.n === 1 ? "" : "s"}`, J_C.gold],
    ["MOST ASSISTS", j.awards.top_assists, (a) => `${a.n} assist${a.n === 1 ? "" : "s"}`, J_C.mint],
    ["PLAYER OF THE TOURNAMENT", j.awards.star, (a) => `${a.n.toFixed(2)} average mark`, "#c77dff"]];
  const aw = (JW - JPAD * 2 - 40) / 3;
  awards.forEach(([title, a, val, colour], i) => {
    const ax = JPAD + i * (aw + 20), ay = y;
    roundRect(ctx, ax, ay, aw, 200, 18, J_C.panel2, colour + "88");
    ctx.save(); ctx.beginPath(); ctx.roundRect(ax, ay, aw, 200, 18); ctx.clip();
    if (awardImgs[i]) { ctx.globalAlpha = 0.08; const s = 190; ctx.drawImage(awardImgs[i], ax + aw - s * 0.75, ay + 20, s, s); ctx.globalAlpha = 1; }
    ctx.restore();
    ctx.fillStyle = colour; ctx.font = '600 15px "JetBrains Mono"'; ctx.fillText(title, ax + 22, ay + 40);
    if (!a) { ctx.fillStyle = J_C.ink3; ctx.font = '700 26px "Archivo"'; ctx.fillText("Nobody", ax + 22, ay + 110); return; }
    ctx.fillStyle = J_C.ink; fitFont(ctx, a.name, 800, 30, '"Archivo"', aw - 44); ctx.fillText(a.name, ax + 22, ay + 100);
    ctx.fillStyle = J_C.ink3; ctx.font = '600 16px "JetBrains Mono"'; ctx.fillText(`${a.short} ${a.season.slice(2)}`, ax + 22, ay + 130);
    ctx.fillStyle = colour; ctx.font = '400 32px "Anton"'; ctx.fillText(val(a), ax + 22, ay + 178);
  });

  // ---- the eleven
  y += awardsH;
  ctx.fillStyle = J_C.gold; ctx.font = '600 18px "JetBrains Mono"'; ctx.fillText("THE ELEVEN", JPAD, y + 30);
  ctx.fillStyle = J_C.ink3; ctx.textAlign = "right"; ctx.fillText("AVERAGE MARK /10", JW - JPAD, y + 30); ctx.textAlign = "left";
  y += 56;
  j.players.forEach((p, i) => {
    const ry = y + i * ROW;
    if (i % 2 === 0) roundRect(ctx, JPAD - 14, ry - 6, JW - JPAD * 2 + 28, ROW - 6, 14, "rgba(255,255,255,.025)");
    medallion(ctx, JPAD + 30, ry + ROW / 2 - 4, 30, crests[i]);
    const nx = JPAD + 80;
    roundRect(ctx, nx, ry + 14, 46, 26, 6, J_C.pos[p.pos]);
    ctx.fillStyle = "#08132b"; ctx.font = '700 15px "JetBrains Mono"'; ctx.textAlign = "center"; ctx.fillText(p.pos, nx + 23, ry + 33); ctx.textAlign = "left";
    ctx.fillStyle = J_C.ink; fitFont(ctx, p.name, 800, 28, '"Archivo"', 470); ctx.fillText(p.name, nx + 58, ry + 37);
    ctx.fillStyle = J_C.ink3; ctx.font = '600 16px "JetBrains Mono"';
    ctx.fillText(`${p.short} ${p.season.slice(2)} · ${p.rating}`, nx + 58, ry + 66);
    const parts = [`${p.apps} apps`];
    if (p.goals) parts.push(`${p.goals} G`);
    if (p.assists) parts.push(`${p.assists} A`);
    const fxp = JPAD + 640;
    ctx.fillStyle = J_C.ink; ctx.font = '700 22px "Archivo"'; ctx.fillText(parts.join(" · "), fxp, ry + 37);
    ctx.fillStyle = J_C.ink2; ctx.font = '600 16px "JetBrains Mono"'; ctx.fillText(roleLine(p), fxp, ry + 66);
    ctx.fillStyle = markColour(p.mark); ctx.font = '400 40px "Anton"'; ctx.textAlign = "right";
    ctx.fillText(p.mark == null ? "–" : p.mark.toFixed(1), JW - JPAD, ry + 56); ctx.textAlign = "left";
  });

  // ---- footer and rim
  y = H - footH;
  ctx.fillStyle = J_C.line; ctx.fillRect(JPAD, y + 10, JW - JPAD * 2, 2);
  ctx.fillStyle = J_C.ink; ctx.font = '400 40px "Anton"'; ctx.fillText("UCLNIGHTS11", JPAD, y + 72);
  ctx.fillStyle = J_C.ink3; ctx.font = '600 16px "JetBrains Mono"'; ctx.textAlign = "right";
  ctx.fillText("MARKS ARE THIS GAME'S OWN · uclnights11.vercel.app", JW - JPAD, y + 68); ctx.textAlign = "left";
  ctx.strokeStyle = side.team; ctx.lineWidth = 8; ctx.strokeRect(4, 4, JW - 8, H - 8);
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
