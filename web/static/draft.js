"use strict";
/* The draft lives in the URL hash (SEED-FORMATION-moves); the server replays it on every
   request and keeps nothing, so a reload or a shared link reproduces the draft exactly.
   Memory mode rides beside it as ?memory=1: it changes what the API shows, not the draft. */

shell("draft");
let S = null;
let busy = false;
const STATE_IN = location.hash.slice(1);
// A link names its own mode; a fresh draft from the nav takes the one last chosen on home.
const MEMORY = new URLSearchParams(location.search).has("memory") || (!STATE_IN && store.get("memory") === "1");
const Q = MEMORY ? "?memory=1" : "";

function setSession(s, fresh = true) {
  S = s;
  history.replaceState(null, "", `/draft${Q}#${s.state}`);
  if (s.complete) { location.href = `/cup#${s.state}`; return; }
  render(fresh);
}

function render(fresh) {
  $("formname").textContent = S.formation.label;
  $("pickno").textContent = S.picks.length + 1;
  $("bar").style.width = `${(S.picks.length / 11) * 100}%`;
  $("memtag").hidden = !S.memory;
  lineChips($("lines"), S.formation, S.xi);
  renderDeal($("deal"), S.deal, {
    rerollsLeft: S.rerolls_left, fresh,
    onTake: (i) => move("pick", { index: i }), onReroll: () => move("reroll"),
  });
  renderPitch($("pitch"), S.formation.slots, S.xi, S.picks.length ? S.picks[S.picks.length - 1].id : null);
  $("xisub").textContent = `${S.picks.length} / 11`;
  xiFoot($("xifoot"), S);
}

async function move(kind, body) {
  if (busy) return;
  busy = true;
  try {
    setSession(await api(`/api/draft/${S.state}/${kind}${Q}`, { method: "POST", body: body ? JSON.stringify(body) : undefined }));
  } catch (e) {
    // A pick is the state plus one move, so sending it again is harmless; no reply just means try again.
    toast(e.status === 0 ? `${e.message}. Your draft is safe; try that pick again.` : e.message);
  } finally { busy = false; }
}

(async function boot() {
  loadMeta().catch(() => {});
  try {
    if (/^[\w.-]+$/.test(STATE_IN)) return setSession(await api(`/api/draft/${STATE_IN}${Q}`));
    const fresh = await api(`/api/draft${Q}`, { method: "POST", body: JSON.stringify({ formation: store.get("formation") || "433" }) });
    setSession(fresh);
  } catch (e) { toast(e.message); }
})();
