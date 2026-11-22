// Case Study 3 central dashboard: every FC's status from history, overrides and the digest log.

const el3 = (id) => document.getElementById(id);

async function loadDashboard() {
  const data = await api("/api/cs3/dashboard?days=31");
  if (!data.fcs.length) {
    el3("dash-latest").innerHTML = `<p class="muted">No data yet. <a href="/case-study-3">Upload a file</a> to start.</p>`;
    el3("dash-grid").innerHTML = "";
    return;
  }
  el3("dash-range").textContent = `(${CS3.dayLabel(data.dates[0])} – ${CS3.dayLabel(data.dates[data.dates.length - 1])})`;

  el3("dash-latest").innerHTML = data.fcs.map((fc) => {
    const latest = data.latest[fc];
    return `<div class="cs3-fc c-border-${latest.colour}">
      <div class="row-between"><b>${escapeHtml(fc)}</b>${CS3.colourBadge(latest.colour)}</div>
      <div class="cs3-fc-cm2">CM2 ${CS3.pct(latest.cm2_pct)}</div>
      <div class="muted small">${CS3.dayLabel(latest.date)} · <a href="/api/cs3/digests/preview?fc=${encodeURIComponent(fc)}" target="_blank">digest</a></div>
    </div>`;
  }).join("");

  CS3.renderGrid(el3("dash-grid"), data.cells, (cell) => {
    el3("dash-detail").classList.remove("hidden");
    el3("dash-detail").innerHTML = CS3.detailHtml(cell);
  });
}

async function loadOverrides() {
  const rows = await api("/api/cs3/overrides");
  el3("ovr-table").innerHTML = `<tr><th>FC</th><th>Line item</th><th>From</th><th>To</th><th>Note</th><th></th></tr>` + (rows.length
    ? rows.map((o) => `<tr><td>${escapeHtml(o.fc)}</td><td>${escapeHtml(o.line_item)}</td><td>${o.date_from}</td><td>${o.date_to}</td>
        <td>${escapeHtml(o.note)}</td><td><a href="#" data-id="${o.id}">remove</a></td></tr>`).join("")
    : `<tr><td colspan="6" class="muted">No known issues recorded.</td></tr>`);
  el3("ovr-table").querySelectorAll("a[data-id]").forEach((a) => a.addEventListener("click", async (e) => {
    e.preventDefault();
    await api(`/api/cs3/overrides/${a.dataset.id}`, { method: "DELETE" });
    loadOverrides();
  }));
}

async function loadLog() {
  const rows = await api("/api/cs3/digests");
  el3("dash-log").innerHTML = `<tr><th>When</th><th>FC</th><th>Day</th><th>Colour</th><th>To</th><th>Channel</th><th>Status</th><th>Detail</th></tr>` + (rows.length
    ? rows.map((r) => `<tr><td class="nowrap">${new Date(r.created_at).toLocaleString()}</td><td>${escapeHtml(r.fc)}</td><td>${r.date}</td>
        <td>${CS3.colourBadge(r.colour)}</td><td>${escapeHtml(r.recipient || "-")}</td><td>${r.channel}</td><td>${r.status}</td>
        <td class="small">${escapeHtml(r.detail || "")}</td></tr>`).join("")
    : `<tr><td colspan="8" class="muted">No digests sent yet.</td></tr>`);
}

el3("ovr-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  el3("ovr-error").textContent = "";
  const body = Object.fromEntries(new FormData(event.target).entries());
  try {
    await api("/api/cs3/overrides", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    event.target.reset();
    loadOverrides();
  } catch (error) {
    el3("ovr-error").textContent = error.message;
  }
});

el3("dash-send").addEventListener("click", async () => {
  el3("dash-send").disabled = true;
  try {
    const result = await api("/api/cs3/digests/send", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    el3("dash-result").innerHTML = `<div class="warning">${result.results.length} digest(s) processed via ${result.channel}.</div>`;
    loadLog();
  } catch (error) {
    el3("dash-result").innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  } finally {
    el3("dash-send").disabled = false;
  }
});

loadDashboard();
loadOverrides();
loadLog();
