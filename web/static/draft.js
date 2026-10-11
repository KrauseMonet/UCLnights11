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
  // A finished bench draft stops to plan its changes (C41); an eleven-pick one kicks off.
  if (s.complete && !s.bench_size) { location.href = `/cup#${s.state}`; return; }
  render(fresh);
}

function render(fresh) {
  if (S.complete) return renderPlan();
  // After the eleven, a bench draft (C40) takes three more for the bench; an eleven-pick
  // draft from an older link has bench_size 0 and looks as it always did.
  const forBench = S.picks.length >= 11;
  $("formname").textContent = S.formation.label;
  $("pickno").textContent = S.picks.length + 1;
  $("picktotal").textContent = S.total;
  $("bar").style.width = `${(S.picks.length / S.total) * 100}%`;
  $("memtag").hidden = !S.memory;
  lineChips($("lines"), S.formation, S.xi);
  renderDeal($("deal"), S.deal, {
    rerollsLeft: S.rerolls_left, fresh,
    heading: forBench ? `For your bench · ${S.picks.length - 10} of ${S.bench_size}` : undefined,
    takeLabel: forBench ? "Bench" : undefined,
    onTake: (i) => move("pick", { index: i }), onReroll: () => move("reroll"),
  });
  renderPitch($("pitch"), S.formation.slots, S.xi, S.picks.length && !forBench ? S.picks[S.picks.length - 1].id : null);
  renderBench($("bench"), S.bench, S.bench_size);
  $("xisub").textContent = S.bench_size ? `${S.xi.length} / 11 · bench ${S.bench.length} / ${S.bench_size}` : `${S.picks.length} / 11`;
  xiFoot($("xifoot"), { ...S, picks: S.picks.slice(0, 11) });
}

/* The plan (C41): for each substitute, from when, on what score and for whom. Every
   change is sent at once and comes back as a new state, so the link always holds the plan. */
function renderPlan() {
  $("formname").textContent = S.formation.label;
  $("progtext").textContent = "Squad complete · your changes";
  $("bar").style.width = "100%";
  $("memtag").hidden = !S.memory;
  lineChips($("lines"), S.formation, S.xi);
  renderPitch($("pitch"), S.formation.slots, S.xi, null);
  renderBench($("bench"), S.bench, S.bench_size);
  $("xisub").textContent = `11 / 11 · bench ${S.bench.length} / ${S.bench_size}`;
  xiFoot($("xifoot"), { ...S, picks: S.picks.slice(0, 11) });
  const line = (i) => S.plan.find((x) => x.on === i);
  const opt = (v, label, on) => `<option value="${v}" ${on ? "selected" : ""}>${esc(label)}</option>`;
  const el = $("deal");
  el.style.cssText = "";
  el.classList.remove("flip");
  el.innerHTML = `
    <div class="panel-h"><span class="label">Your changes</span><span class="label">${S.plan_chosen ? "your plan" : "automatic plan"}</span></div>
    <div class="plan-intro"><p>Players tire as a match goes on, and a tired man defends worst. A substitute comes on fresh.
      Up to three changes, the same plan for every match. The score is the tie's: in a second leg, the aggregate.</p></div>
    ${S.bench.map((c, i) => {
      const x = line(i);
      return `<div class="plan-row" data-i="${i}">
        <div class="t">${crest(c.crest, 36, c.club)}<div class="who"><b>${esc(c.name)}</b><small>${(c.positions || [c.pos]).map(posChip).join("")}${c.rating == null ? "" : ` ${c.rating}`}</small></div></div>
        <label>On<select data-k="minute" aria-label="When ${esc(c.name)} comes on">${opt("", "Not used", !x)}${[45, 50, 55, 60, 65, 70, 75, 80, 85].map((m) => opt(m, `from ${m}'`, x && x.minute === m)).join("")}</select></label>
        <label>When<select data-k="when" ${x ? "" : "disabled"}>${Object.entries(WHEN_SHORT).map(([k, l]) => opt(k, l, x ? x.when === k : k === "any")).join("")}</select></label>
        <label>For<select data-k="off" ${x ? "" : "disabled"}>${opt("", "best change", !x || x.off == null)}${c.can_replace.map((j) =>
          opt(j, `${S.xi[j].slot} · ${S.xi[j].name}`, x && x.off === j)).join("")}</select></label>
      </div>`;
    }).join("")}
    <div class="plan-foot">
      <a class="btn primary" href="/cup#${S.state}">Kick off</a>
      <button class="btn ghost" id="autoplan" ${S.plan_chosen ? "" : "disabled"}>Use the automatic plan</button>
      <p class="label">Automatic: the best-rated on first, at 60', 70' and 80'. "Best change" replaces whoever it helps most to replace, and only if it helps.</p>
    </div>`;
  el.querySelectorAll("select").forEach((sel) => sel.onchange = sendPlan);
  $("autoplan").onclick = () => postPlan(null);
}

function sendPlan() {
  const changes = [...document.querySelectorAll(".plan-row")].map((row) => {
    const v = (k) => row.querySelector(`[data-k="${k}"]`).value;
    if (!v("minute")) return null;
    return { on: +row.dataset.i, minute: +v("minute"), when: v("when"), off: v("off") === "" ? null : +v("off") };
  }).filter(Boolean);
  // Two changes for one man can't both happen; the later one goes back to "whoever".
  const seen = new Set();
  changes.forEach((x) => { if (x.off != null) { if (seen.has(x.off)) x.off = null; else seen.add(x.off); } });
  postPlan(changes);
}

async function postPlan(changes) {
  if (busy) return;
  busy = true;
  try {
    setSession(await api(`/api/draft/${S.state}/plan${Q}`, { method: "POST", body: JSON.stringify({ changes }) }), false);
  } catch (e) { toast(e.message); render(false); } finally { busy = false; }
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
    // A new draft is set up on its own page first (formation and ratings, C37).
    location.replace("/start");
  } catch (e) { toast(e.message); }
})();
