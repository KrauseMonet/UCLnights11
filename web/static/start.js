"use strict";
/* The setup page (C37): a formation and whether ratings show, chosen before the first deal.
   The pitch on the right draws the formation's slots as you choose (or hover), and the
   choices are remembered for next time. Starting asks the API for a fresh draft. */

shell("draft");
let FORMATION = store.get("formation");
let MEMORY = store.get("memory") === "1";
// A dynasty (C64) is ten seasons with one squad, each man ageing into his next real season;
// it shows ratings, since a window's whole point is seeing who rose and who fell.
let DYNASTY = store.get("dynasty") === "1";
let BY = {};
const GROUPS = [[4, "Four at the back"], [3, "Three at the back"], [5, "Five at the back"]];

function backLine(f) { return f.slots.filter((s) => LINE_OF[s] === "DF").length; }

function renderForms() {
  const fs = META.formations;
  $("formgroups").innerHTML = GROUPS.map(([n, title]) => {
    const here = fs.filter((f) => backLine(f) === n);
    return here.length ? `<div class="fgroup"><div class="label">${title}</div>
      <div class="fcards" role="radiogroup" aria-label="${title}">${here.map((f) => `
        <button class="fcard" role="radio" aria-checked="${f.code === FORMATION}" data-f="${f.code}">
          <b>${esc(f.label)}</b><small>${f.slots.filter((s) => !["GK", "DF"].includes(LINE_OF[s])).join(" · ")}</small>
        </button>`).join("")}</div></div>` : "";
  }).join("");
  const box = $("formgroups");
  box.onclick = (e) => {
    const b = e.target.closest(".fcard");
    if (!b) return;
    FORMATION = b.dataset.f;
    store.set("formation", FORMATION);
    box.querySelectorAll(".fcard").forEach((c) => c.setAttribute("aria-checked", c.dataset.f === FORMATION));
    preview(FORMATION);
    summary();
  };
  // Hovering a shape previews it; leaving the list shows the chosen one again.
  box.onmouseover = (e) => { const b = e.target.closest(".fcard"); if (b) preview(b.dataset.f); };
  box.onmouseleave = () => preview(FORMATION);
}

function preview(code) {
  const f = BY[code];
  shapePitch($("pitch"), f);
  $("pv-label").textContent = f.label;
  $("pv-name").textContent = f.label;
  $("pv-about").textContent = f.about;
  const names = { DF: "Defence", MF: "Midfield", FW: "Attack" };
  $("pv-lines").innerHTML = ["DF", "MF", "FW"].filter((ln) => f.lines[ln]).map((ln) =>
    `<div><span class="label">${names[ln]}</span>${f.slots.filter((s) => LINE_OF[s] === ln).map(posChip).join("")}</div>`).join("");
}

function renderMemory() {
  if (DYNASTY) {
    $("memory").innerHTML = `<button class="ocard" role="radio" aria-checked="true" disabled><b>Shown</b>
      <small>A dynasty shows every rating: each summer you see who rose and who fell.</small></button>`;
    return;
  }
  const opts = [[false, "Shown", "See every rating while you pick."],
                [true, "Hidden · Memory", "Pick on what you remember. Ratings appear when the tournament starts."]];
  $("memory").innerHTML = opts.map(([m, title, text]) =>
    `<button class="ocard" role="radio" aria-checked="${m === MEMORY}" data-m="${m ? 1 : 0}"><b>${title}</b><small>${text}</small></button>`).join("");
  $("memory").onclick = (e) => {
    const b = e.target.closest(".ocard");
    if (!b) return;
    MEMORY = b.dataset.m === "1";
    store.set("memory", MEMORY ? "1" : "0");
    renderMemory();
    summary();
  };
}

function renderMode() {
  const opts = [[false, "One tournament", "Draft fourteen and play one league phase and knockouts."],
                [true, "Dynasty · ten seasons", "Keep your squad season after season. Each man moves on to his next real season, or leaves, and a transfer window fills the gaps."]];
  $("mode").innerHTML = opts.map(([d, title, text]) =>
    `<button class="ocard" role="radio" aria-checked="${d === DYNASTY}" data-d="${d ? 1 : 0}"><b>${title}</b><small>${text}</small></button>`).join("");
  $("mode").onclick = (e) => {
    const b = e.target.closest(".ocard");
    if (!b) return;
    DYNASTY = b.dataset.d === "1";
    store.set("dynasty", DYNASTY ? "1" : "0");
    renderMode();
    renderMemory();
    summary();
  };
}

function summary() {
  $("summary").textContent = DYNASTY
    ? `${BY[FORMATION].label} · a dynasty of ten seasons · a bench of three · two rerolls a window`
    : `${BY[FORMATION].label} · ratings ${MEMORY ? "hidden" : "shown"} · a bench of three · two rerolls`;
  $("start").textContent = DYNASTY ? "Start the dynasty" : "Start the draft";
}

$("start").onclick = async (e) => {
  e.target.disabled = true;
  try {
    if (DYNASTY) {
      const s = await api("/api/dynasty", { method: "POST", body: JSON.stringify({ formation: FORMATION }) });
      location.href = `/dynasty#${s.state}`;
      return;
    }
    const q = MEMORY ? "?memory=1" : "";
    const s = await api(`/api/draft${q}`, { method: "POST", body: JSON.stringify({ formation: FORMATION }) });
    location.href = `/draft${q}#${s.state}`;
  } catch (err) { toast(err.message); e.target.disabled = false; }
};

(async function boot() {
  renderMode();
  renderMemory();
  try { await loadMeta(); } catch { toast("Could not reach the server"); return; }
  BY = Object.fromEntries(META.formations.map((f) => [f.code, f]));
  if (!BY[FORMATION]) FORMATION = META.default_formation;
  renderForms();
  preview(FORMATION);
  summary();
  $("start").disabled = false;
})();
