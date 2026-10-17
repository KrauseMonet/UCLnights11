"use strict";
/* The profile (C31): one account's saved tournaments and daily challenges, added up.
   Everything here was worked out by the server replaying each result when it was saved. */

shell("profile");
const PF_GOLD = "#c08a1e";   // the analysis's validated gold for a single series (C28)

const sourceLabel = { solo: "Solo", room: "Room", daily: "Daily", dynasty: "Dynasty" };
// A dynasty's season (C66) is keyed by the dynasty's state up to it, so its place is its block count.
const resultHref = (r) => r.source === "solo" ? `/cup#${r.key}` : r.source === "room" ? `/cup?room=${r.key}`
  : r.source === "dynasty" ? `/cup?season=${r.key.split("~").length}#${r.key}` : `/daily#${r.key}`;
const when = (iso) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

function tiles(p) {
  const t = [
    [p.tournaments, "Tournaments"], [p.titles, "Titles"], [p.finals, "Finals"], [p.best_finish || "–", "Best finish"],
    [p.matches ? `${Math.round((p.won / p.matches) * 100)}%` : "–", "Matches won"],
    [p.daily.played, `Dailies · ${p.daily.met} met`], [p.daily.streak, `Daily streak · best ${p.daily.best_streak}`],
  ];
  return `<div class="an-tiles pf-tiles">${t.map(([v, l]) => `<div class="an-tile"><b class="${/^[\d%–]+$/.test(String(v)) ? "" : "txt"}">${esc(String(v))}</b><span>${esc(l)}</span></div>`).join("")}</div>`;
}

/* How far you get: one bar per finish, single series, numbers on the bars. */
function finishesHtml(p) {
  const top = Math.max(1, ...p.finishes.map((f) => f.n));
  return `<section class="panel an-panel"><div class="panel-h pf-ph"><span class="label">How far you get</span><span class="label">${p.tournaments} tournament${p.tournaments === 1 ? "" : "s"}</span></div>
    <div class="pf-finishes">${p.finishes.map((f) => `<div class="pf-fin" title="${esc(f.stage)}: ${f.n}">
      <span class="pf-fin-l">${esc(f.stage)}</span><div class="an-hbar"><i style="width:${(f.n / top) * 100}%;background:${PF_GOLD}"></i><b>${f.n}</b></div></div>`).join("")}</div></section>`;
}

function boardHtml(title, rows, fmt, note = "") {
  const lead = rows.length ? rows[0].value : 1;
  return `<div class="panel an-board"><div class="panel-h"><span class="label">${title}</span>${note ? `<small class="an-note">${note}</small>` : ""}</div>
    ${rows.length ? `<ol>${rows.map((r) => `<li>${crest(r.crest, 22, r.name)}<div class="who"><b>${esc(r.name)}</b>
      <small>${r.pos} · ${r.apps} app${r.apps === 1 ? "" : "s"}</small><div class="an-lead"><i style="width:${(r.value / lead) * 100}%"></i></div></div>
      <span class="n">${fmt(r.value)}</span></li>`).join("")}</ol>` : `<p class="empty">Nothing yet.</p>`}</div>`;
}

function recentHtml(p) {
  if (!p.recent.length) return `<section class="panel gate"><div><h2>Nothing saved yet</h2>
    <p>Finish a tournament you drafted here, or a friends' room, and it saves itself; a link someone sent you saves with <b>Save to profile</b>. Today's daily challenge saves itself too.</p></div>
    <div class="gate-cta"><a class="btn primary" href="/daily">Today's challenge</a><a class="btn ghost" href="/draft">Start a draft</a></div></section>`;
  return `<section class="panel"><div class="panel-h"><span class="label">Recent</span><span class="label">tap to see it again</span></div>
    ${p.recent.map((r) => `<a class="myroom pf-row" href="${esc(resultHref(r))}">
      <span class="pill ${r.champion || r.reached === "Goal met" ? "complete" : ""}">${sourceLabel[r.source]}</span>
      <span><b>${esc(r.reached)}</b><small>${r.record.join("-")} · ${r.gf}–${r.ga} · ${esc(r.formation)}${r.star ? ` · star ${esc(r.star)}` : ""}</small></span>
      <span class="pf-when">${esc(when(r.at))}</span></a>`).join("")}</section>`;
}

/* Each dynasty with a season saved (C66): how far it has got and what it has won. */
function dynastiesHtml(p) {
  if (!p.dynasties.length) return "";
  return `<section class="panel"><div class="panel-h"><span class="label">Dynasties</span><span class="label">${p.dynasties.length}</span></div>
    ${p.dynasties.map((d) => `<a class="myroom pf-row" href="/dynasty#${esc(d.latest)}">
      <span class="pill ${d.titles ? "complete" : ""}">Year ${d.year}</span>
      <span><b>${d.titles} title${d.titles === 1 ? "" : "s"} · ${d.finals} final${d.finals === 1 ? "" : "s"}</b>
        <small>${d.seasons} season${d.seasons === 1 ? "" : "s"} saved · best ${esc(d.best)} · seed ${esc(d.seed)}</small></span>
      <span class="pf-when">${esc(when(d.at))}</span></a>`).join("")}</section>`;
}

function render(p) {
  $("pfhero").innerHTML = `<div class="kicker">Profile · since ${esc(when(p.member_since))}</div>
    <h1 class="arch-h">${esc(p.username)}</h1>${tiles(p)}`;
  $("pfbody").innerHTML = `<div class="cup-grid pf-grid">
    <div class="cup-stack">${recentHtml(p)}</div>
    <div class="cup-stack">${finishesHtml(p)}${dynastiesHtml(p)}</div></div>
    <h2 class="h2">Your players</h2><p class="sub">Across every saved tournament and daily challenge.</p>
    <div class="an-boards">
      ${boardHtml("Goals", p.boards.goals, (v) => v)}
      ${boardHtml("Assists", p.boards.assists, (v) => v)}
      ${boardHtml("Most picked", p.boards.picked, (v) => v)}
      ${boardHtml("Average mark", p.boards.mark, (v) => v.toFixed(2), `${p.min_apps_for_mark}+ apps`)}
    </div>
    <div id="pfdyn"></div>`;
  dynastyLegacies(p);
}

/* Each recent dynasty's legacy (C67): its legends, team of the dynasty and top scorers, as
   its own page shows them. Asked for with its latest saved state, and a season is saved only
   once watched to the end, so nothing here is a result not yet seen. Fetched after the rest
   of the profile is drawn: a dynasty's legacy replays every one of its seasons. */
const DYNASTIES_SHOWN = 3;
async function dynastyLegacies(p) {
  const shown = p.dynasties.slice(0, DYNASTIES_SHOWN);
  if (!shown.length) return;
  const got = await Promise.all(shown.map((d) => api(`/api/dynasty/${d.latest}/legacy`).catch(() => null)));
  const el = $("pfdyn");
  if (!el) return;
  const rows = shown.map((d, k) => [d, got[k], k]).filter(([, L]) => L);
  if (!rows.length) return;
  el.innerHTML = `<h2 class="h2">Your dynasties</h2>
    <p class="sub">Legends, the team of each dynasty and its scorers, over the seasons you've saved.${p.dynasties.length > shown.length ? ` The ${shown.length} most recent.` : ""}</p>
    ${rows.map(([d, L, k]) => `<div class="pf-dyn">
      <div class="pf-dyn-h"><h3>Seed ${esc(d.seed)} · Year ${d.year}</h3>
        <span class="label">${d.titles} title${d.titles === 1 ? "" : "s"} · ${d.finals} final${d.finals === 1 ? "" : "s"}</span>
        <a class="btn ghost small" href="/dynasty#${esc(d.latest)}">Open the dynasty</a></div>
      ${legacyHtml(L, `pfteam${k}`)}</div>`).join("")}`;
  rows.forEach(([, L, k]) => legacyPitch(L, $(`pfteam${k}`)));
}

function signedOut() {
  $("pfhero").innerHTML = `<div class="kicker">Profile</div><h1 class="arch-h">Your nights</h1>`;
  $("pfbody").innerHTML = `<section class="panel gate"><div><h2>Sign in to see your profile</h2>
    <p>Saved tournaments, titles, your daily streak and the players who carried you.</p></div>
    <div class="gate-cta"><button class="btn primary" id="gin">Sign in</button><button class="btn ghost" id="gup">Create an account</button></div></section>`;
  $("gin").onclick = () => openAuth("in");
  $("gup").onclick = () => openAuth("up");
}

/* Not on your profile yet (C46): tournaments from before a finished one saved itself.
   The server keeps no solo run, so this browser names the solo links it has opened (the
   cup page's cup:<link> marks); the server adds the rooms you sat in and leaves out what
   is saved. A link a friend sent you may be among them, so each row can be saved alone. */
function browserLinks() {
  const out = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith("cup:") && !k.startsWith("cup:room:")) out.push(k.slice(4));
    }
  } catch { /* storage blocked: no solo links to offer */ }
  return out;
}

async function unsavedPanel() {
  let u;
  try { u = await api("/api/results/unsaved", { method: "POST", body: JSON.stringify({ keys: browserLinks() }) }); }
  catch { return; }
  const rows = [...u.rooms.map((r) => ({ source: "room", key: r.code, title: `Room ${r.code}`, sub: r.format })),
                ...u.solo.map((r) => ({ source: "solo", key: r.key, title: `Seed ${r.seed}`, sub: r.formation }))];
  if (!rows.length) return;
  const box = document.createElement("section");
  box.className = "panel";
  box.id = "pfunsaved";
  $("pfunsaved")?.remove();   // a second refresh may land first
  box.innerHTML = `<div class="panel-h"><span class="label">Not on your profile yet</span>
      <button class="btn primary" id="saveall">Save all ${rows.length}</button></div>
    <p class="sub pf-unsaved-note">Finished before tournaments saved themselves. Solo runs are the ones opened in this browser; leave out any a friend sent you.</p>
    ${rows.map((r, i) => `<div class="myroom pf-row" data-i="${i}">
      <span class="pill">${sourceLabel[r.source]}</span>
      <span><b><a href="${esc(resultHref(r))}">${esc(r.title)}</a></b><small>${esc(r.sub)}</small></span>
      <button class="btn ghost" data-save="${i}">Save</button></div>`).join("")}`;
  $("pfbody").prepend(box);
  const saveOne = async (i) => {
    const btn = box.querySelector(`[data-save="${i}"]`);
    if (btn.disabled) return true;
    btn.disabled = true;
    try {
      await api("/api/results", { method: "POST", body: JSON.stringify({ source: rows[i].source, key: rows[i].key }) });
      btn.textContent = "Saved ✓";
      return true;
    } catch (e) { btn.disabled = false; toast(e.message); return false; }
  };
  box.querySelectorAll("[data-save]").forEach((b) => b.onclick = async () => { if (await saveOne(+b.dataset.save)) refresh(); });
  $("saveall").onclick = async () => {
    $("saveall").disabled = true;
    let ok = 0;
    for (let i = 0; i < rows.length; i++) if (await saveOne(i)) ok++;
    toast(`Saved ${ok} to your profile`);
    refresh();
  };
}

async function refresh() {
  try { render(await api("/api/profile")); }
  catch (e) { $("pfbody").innerHTML = `<p class="sub">${esc(e.message)}</p>`; return; }
  unsavedPanel();
}

onAuth((me) => me ? refresh() : signedOut());
