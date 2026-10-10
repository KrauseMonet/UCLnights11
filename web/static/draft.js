"use strict";
/* The draft lives in the URL hash (SEED-FORMATION-moves); the server replays it on every
   request and keeps nothing, so a reload or a shared link reproduces the draft exactly. */

shell("draft");
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
  renderDeal($("deal"), S.deal, {
    rerollsLeft: S.rerolls_left, fresh,
    onTake: (i) => move("pick", { index: i }), onReroll: () => move("reroll"),
  });
  renderPitch($("pitch"), S.formation.code, S.picks, S.picks.length ? S.picks[S.picks.length - 1].id : null);
  const avg = S.picks.length ? Math.round(S.picks.reduce((a, c) => a + c.rating, 0) / S.picks.length) : "–";
  const clubs = new Set(S.picks.map((c) => c.club)).size;
  $("xisub").textContent = `${S.picks.length} / 11`;
  $("xifoot").innerHTML = `<div><b>${avg}</b>Average</div><div><b>${clubs}</b>Clubs</div><div><b>${S.rerolls_left}</b>Rerolls left</div>`;
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
