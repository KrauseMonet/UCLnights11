"use strict";
/* The admin page. Everything here is guarded by the API (web.admin), which answers 404
   to anyone not named in ADMIN_ACCOUNT_IDS; this page only draws what it is given. */

shell("admin");

const when = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function denied() {
  $("adminh").textContent = "Not here";
  $("admin").hidden = true;
}

async function loadOverview() {
  const o = await api("/api/admin/overview");
  $("astats").innerHTML = [
    [o.accounts, "Accounts"], [o.accounts_this_week, "New this week"],
    [o.rooms.lobby, "Lobbies"], [o.rooms.drafting, "Drafting"], [o.rooms.complete, "Finished"],
  ].map(([n, l]) => `<div><b>${n}</b>${l}</div>`).join("");
  const top = Math.max(1, ...o.signups.map((d) => d.n));
  $("signups").innerHTML = o.signups.map((d) => `<div class="bar-col" title="${esc(d.day)}: ${d.n}">
      <i style="height:${(d.n / top) * 100}%"></i><span>${d.n}</span><small>${esc(d.day.slice(8))}</small></div>`).join("");
  $("flist").innerHTML = o.failures.length ? `<table class="admin-table"><tbody>${o.failures.map((f) => `
      <tr><td class="num">${f.count}</td><td><span class="pill">${esc(f.kind)}</span></td><td class="code-sm">${esc(f.page)}</td>
        <td class="detail">${esc(f.detail)}<small>${when(f.last)}</small></td></tr>`).join("")}</tbody></table>`
    : `<p class="empty">Nothing reported.</p>`;
}

async function loadAccounts(q = "") {
  const { accounts } = await api(`/api/admin/accounts?q=${encodeURIComponent(q)}`);
  $("alist").innerHTML = accounts.length ? accounts.map((a) => `
    <div class="myroom admin-row">
      <span class="acct-init" aria-hidden="true">${esc(a.username[0].toUpperCase())}</span>
      <span><b>${esc(a.username)}</b> <small>#${a.id}</small><small>${esc(a.email)} · ${when(a.created_at)}</small>
        <small>${a.rooms} room${a.rooms === 1 ? "" : "s"}${a.hosting ? ` · hosts ${a.hosting}` : ""}</small></span>
      <span class="admin-acts">
        <button class="btn ghost small" data-pw="${a.id}" data-name="${esc(a.username)}">Set password</button>
        ${a.id === ME.id ? "" : `<button class="btn ghost small danger" data-del="${a.id}" data-name="${esc(a.username)}">Delete</button>`}</span>
    </div>`).join("") : `<p class="empty">No accounts match.</p>`;
  $("alist").querySelectorAll("[data-pw]").forEach((b) => b.onclick = async () => {
    const pw = prompt(`New password for ${b.dataset.name} (8 or more characters). Pass it on to them yourself.`);
    if (!pw) return;
    try { await api(`/api/admin/accounts/${b.dataset.pw}/password`, { method: "POST", body: JSON.stringify({ password: pw }) }); toast("Password set"); }
    catch (e) { toast(e.message); }
  });
  $("alist").querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => {
    if (prompt(`Delete ${b.dataset.name}? Their rooms pass to the next player. Type the username to confirm.`) !== b.dataset.name) return;
    try { await api(`/api/admin/accounts/${b.dataset.del}`, { method: "DELETE" }); toast("Account deleted"); refresh(); }
    catch (e) { toast(e.message); }
  });
}

async function loadRooms() {
  const { rooms } = await api("/api/admin/rooms");
  $("rlist").innerHTML = rooms.length ? rooms.map((r) => `
    <div class="myroom admin-row">
      <a class="code-sm" href="/room#${esc(r.code)}">${esc(r.code)}</a>
      <span>${r.players} of ${r.size}${r.memory ? " · Memory" : ""}<small>host ${esc(r.host)} · ${when(r.updated_at)}</small></span>
      <span class="pill ${esc(r.status)}">${esc(r.status)}</span>
      <button class="btn ghost small danger" data-room="${esc(r.code)}">Delete</button>
    </div>`).join("") : `<p class="empty">No rooms.</p>`;
  $("rlist").querySelectorAll("[data-room]").forEach((b) => b.onclick = async () => {
    if (!confirm(`Delete room ${b.dataset.room} for everyone in it?`)) return;
    try { await api(`/api/admin/rooms/${b.dataset.room}`, { method: "DELETE" }); toast("Room deleted"); loadRooms(); }
    catch (e) { toast(e.message); }
  });
}

/* The daily challenge (C55): a day's challenge and attempts, and the three fixes: let one
   account play again, clear everyone's attempts (the same challenge, open again), or make
   today again (new squads, opponent and goal). Tomorrow's never shows, even here. */
let DAY = null;

function drawDaily(d) {
  DAY = d.day;
  const fmt = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  const days = d.days.some((x) => x.day === d.day) ? d.days : [{ day: d.day, edition: 0, entries: 0, met: 0 }, ...d.days];
  $("dday").innerHTML = days.map((x) => `<option value="${esc(x.day)}" ${x.day === d.day ? "selected" : ""}>
    ${esc(fmt(x.day))}${x.day === d.now ? " (today)" : ""} · ${x.entries} played</option>`).join("");
  const c = d.challenge;
  $("dsum").innerHTML = c ? `<div class="admin-dsum">
      <p><b>${esc(c.goal)}</b> against <b>${esc(c.opponent)}</b> · ${esc(c.formation)}${c.bench ? " with a bench" : ""}</p>
      <p class="label">Measured ${c.success_rate}% · ${d.rows.length} played, ${d.rows.filter((r) => r.met).length} met the goal
        · ${c.edition ? `made again ${c.edition === 1 ? "once" : `${c.edition} times`}, last ${when(c.made_at)}` : `made ${when(c.made_at)}`}</p>
      <div class="admin-acts">
        <button class="btn ghost small danger" id="dclear" ${d.rows.length ? "" : "disabled"}>Clear all attempts</button>
        ${d.today ? `<button class="btn ghost small danger" id="dremake">Make today again</button>` : ""}</div></div>`
    : `<p class="empty">No challenge was made for this day.</p>`;
  $("dlist").innerHTML = d.rows.length ? `<table class="admin-table"><tbody>${d.rows.map((r, n) => `
      <tr><td class="num">${n + 1}</td><td><b>${esc(r.username)}</b> <small>#${r.id}</small></td>
        <td>${r.met ? "Met" : "Missed"} · ${r.gf}–${r.ga}${r.mark == null ? "" : ` · ${r.mark.toFixed(2)}`}${r.sheet ? " · own sheet" : ""}
          <small>${when(r.submitted_at)}</small></td>
        <td class="admin-acts"><button class="btn ghost small" data-reset="${r.id}" data-name="${esc(r.username)}">${d.today ? "Let play again" : "Remove"}</button></td></tr>`).join("")}</tbody></table>`
    : c ? `<p class="empty">Nobody has played this day.</p>` : "";
  if ($("dclear")) $("dclear").onclick = async () => {
    if (!confirm(`Clear all ${d.rows.length} attempts at ${d.day}? ${d.today ? "Everyone can play again; the challenge stays the same." : "That day's table and everyone's saved result go."}`)) return;
    try { const r = await api(`/api/admin/daily/clear?day=${d.day}`, { method: "POST" }); drawDaily(r); toast(`${r.cleared} cleared`); }
    catch (e) { toast(e.message); }
  };
  if ($("dremake")) $("dremake").onclick = async () => {
    if (prompt(`Make today's challenge again? New squads, a new opponent and goal; all ${d.rows.length} attempts are cleared, and anyone mid-draft starts over. Type "new day" to confirm.`) !== "new day") return;
    const b = $("dremake");
    b.disabled = true; b.textContent = "Measuring…";
    try { const r = await api("/api/admin/daily/remake", { method: "POST" }); drawDaily(r); toast("Today is made again"); }
    catch (e) { toast(e.message); b.disabled = false; b.textContent = "Make today again"; }
  };
  $("dlist").querySelectorAll("[data-reset]").forEach((b) => b.onclick = async () => {
    if (!confirm(`${d.today ? "Let" : "Remove"} ${b.dataset.name}'s attempt at ${d.day}${d.today ? " play again" : ""}? Their result goes from the table and their profile.`)) return;
    try { await api(`/api/admin/daily/${b.dataset.reset}?day=${d.day}`, { method: "DELETE" }); toast("Attempt removed"); loadDaily(d.day); }
    catch (e) { toast(e.message); }
  });
}

async function loadDaily(day = DAY) {
  drawDaily(await api(`/api/admin/daily${day ? `?day=${day}` : ""}`));
}

$("dday").onchange = () => loadDaily($("dday").value).catch((e) => toast(e.message));

function refresh() { return Promise.all([loadOverview(), loadDaily(), loadAccounts($("aq").value), loadRooms()]); }

$("asearch").onsubmit = (e) => { e.preventDefault(); loadAccounts($("aq").value).catch((err) => toast(err.message)); };

onAuth(async (me) => {
  if (!me || !me.admin) return denied();
  try {
    await refresh();
    $("adminh").textContent = "The site";
    $("admin").hidden = false;
  } catch (e) { if (e.status === 404) denied(); else toast(e.message); }
});
