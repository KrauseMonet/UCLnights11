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

function refresh() { return Promise.all([loadOverview(), loadAccounts($("aq").value), loadRooms()]); }

$("asearch").onsubmit = (e) => { e.preventDefault(); loadAccounts($("aq").value).catch((err) => toast(err.message)); };

onAuth(async (me) => {
  if (!me || !me.admin) return denied();
  try {
    await refresh();
    $("adminh").textContent = "The site";
    $("admin").hidden = false;
  } catch (e) { if (e.status === 404) denied(); else toast(e.message); }
});
