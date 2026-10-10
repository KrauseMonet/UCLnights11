"use strict";
/* The draft lives in the URL hash (SEED-FORMATION-moves); the server replays it on every
   request and keeps nothing, so a reload or a shared link reproduces the draft exactly. */

shell("draft");
const LINES = { GK: "Goalkeepers", DF: "Defenders", MF: "Midfielders", FW: "Forwards" };
let S = null;
let busy = false;

function setSession(s, fresh = true) {
  S = s;
  history.replaceState(null, "", `#${s.state}`);
  if (s.complete) { location.href = `/cup#${s.state}`; return; }
  render(fresh);
}

function render(fresh) {
  $("formname").textContent = S.formation.label;
  $("pickno").textContent = S.picks.length + 1;
  $("bar").style.width = `${(S.picks.length / 11) * 100}%`;
  renderDeal(S.deal, fresh);
  renderPitch($("pitch"), S.formation.code, S.picks, S.picks.length ? S.picks[S.picks.length - 1].id : null);
  const avg = S.picks.length ? Math.round(S.picks.reduce((a, c) => a + c.rating, 0) / S.picks.length) : "–";
  const clubs = new Set(S.picks.map((c) => c.club)).size;
  $("xisub").textContent = `${S.picks.length} / 11`;
  $("xifoot").innerHTML = `<div><b>${avg}</b>Average</div><div><b>${clubs}</b>Clubs</div><div><b>${S.rerolls_left}</b>Rerolls left</div>`;
}

function renderDeal(d, fresh) {
  const el = $("deal");
  const byLine = { GK: [], DF: [], MF: [], FW: [] };
  d.cards.forEach((c, i) => byLine[c.pos].push([c, i]));
  const open = d.cards.filter((c) => c.takeable).length;
  const rows = Object.entries(byLine).filter(([, cs]) => cs.length).map(([pos, cs]) =>
    `<div class="line-h">${LINES[pos]}</div>` + cs.map(([c, i]) => `
      <div class="row ${c.takeable ? "" : "off"}">
        <span class="pos ${c.pos}">${c.pos}</span>
        <div class="who"><b>${esc(c.name)}</b><small>${esc(c.nation || "")}</small></div>
        ${rate(c.rating)}
        ${c.takeable ? `<button class="take" data-i="${i}" aria-label="Take ${esc(c.name)}">Take</button>`
                     : `<span class="why">${esc(c.reason)}</span>`}
      </div>`).join("")).join("");
  el.style.cssText = teamStyle(d);
  el.innerHTML = `
    <div class="panel-h"><span class="label">Dealt to you</span><span class="label"><b>${open}</b> of ${d.cards.length} available</span></div>
    <div class="band">
      ${crest(d.crest, 104, d.name)}
      <div class="deal-year">${esc(d.season)}</div>
      <div class="deal-club">${esc(d.name)}</div>
      <div class="deal-actions">
        <button class="btn small" id="reroll" ${S.rerolls_left ? "" : "disabled"}>Another squad</button>
        <span class="label" style="color:rgba(255,255,255,.65)">${S.rerolls_left} left</span>
      </div>
    </div>
    <div>${rows}</div>`;
  if (fresh) { el.classList.remove("flip"); void el.offsetWidth; el.classList.add("flip"); }
  el.querySelectorAll(".take").forEach((b) => b.onclick = () => move(`pick`, { index: +b.dataset.i }));
  $("reroll").onclick = () => move("reroll");
}

async function move(kind, body) {
  if (busy) return;
  busy = true;
  try {
    setSession(await api(`/api/draft/${S.state}/${kind}`, { method: "POST", body: body ? JSON.stringify(body) : undefined }));
  } catch (e) { toast(e.message); } finally { busy = false; }
}

(async function boot() {
  loadMeta().catch(() => {});
  const state = location.hash.slice(1);
  try {
    if (/^[\w.-]+$/.test(state)) return setSession(await api(`/api/draft/${state}`));
    const fresh = await api("/api/draft", { method: "POST", body: JSON.stringify({ formation: store.get("formation") || "433" }) });
    setSession(fresh);
  } catch (e) { toast(e.message); }
})();
