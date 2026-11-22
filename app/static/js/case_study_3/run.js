// Case Study 3 run page: progress, summary, colour grid, tables and digests for one upload.

const runId = document.getElementById("cs3-run").dataset.runId;
const $ = (id) => document.getElementById(id);
const runState = { tab: "insights", fc: "", colour: "", severity: "", days: [] };

// ---------------------------------------------------------------- progress

async function pollRun() {
  let run;
  try {
    run = await api(`/api/cs3/runs/${runId}`);
  } catch (error) {
    return showRunError(error.message);
  }
  $("run-title").textContent = `FC P&L analysis · ${run.filename}`;
  $("run-file").textContent = run.options.send_digests ? "Digests will be sent when processing finishes." : "";
  $("run-status").textContent = run.status;
  $("run-status").className = `pill ${run.status}`;
  $("run-progress").style.width = `${run.progress || 0}%`;
  $("run-message").textContent = run.message || "";

  if (run.status === "completed") return showRunResults(run);
  if (run.status === "failed") return showRunError(run.error || run.message);
  setTimeout(pollRun, 1200);
}

function showRunError(message) {
  $("run-error").classList.remove("hidden");
  $("run-error-text").textContent = message;
}

// ---------------------------------------------------------------- results

async function showRunResults(run) {
  $("run-results").classList.remove("hidden");
  $("run-download").href = `/api/cs3/runs/${runId}/report`;
  const s = run.summary;

  const tile = (label, value, cls = "") => `<div class="cs3-tile ${cls}"><b>${value}</b><span>${label}</span></div>`;
  $("run-tiles").innerHTML =
    tile("FC-days", s.fc_days) + tile("FCs", s.fcs.length) +
    ["Red", "Yellow", "Green", "Blue"].map((c) => tile(`${c} days`, s.colours[c], `c-${c}`)).join("") +
    tile("Flags (high / medium / low)", `${s.severity.high} / ${s.severity.medium} / ${s.severity.low}`);

  const scenarios = ["clean day", "line-item-only breach", "CM1 breach", "CM2 breach", "suspiciously high CM2"];
  $("run-scenarios").innerHTML = "Scenarios found: " + scenarios.map((name) =>
    `<span class="chip-plain">${name}: <b>${s.scenarios[name] || 0}</b></span>`).join("");

  $("run-warnings").innerHTML = (run.warnings || []).map((w) => `<div class="warning">${escapeHtml(w)}</div>`).join("") +
    (s.targets_source === "file" ? "" : `<div class="warning">No target sheet in the file - default target ranges were used.</div>`);

  runState.days = await api(`/api/cs3/runs/${runId}/days`);
  CS3.renderGrid($("run-grid"), runState.days, (cell) => {
    $("run-detail").classList.remove("hidden");
    $("run-detail").innerHTML = CS3.detailHtml(cell);
  });

  $("run-fc").innerHTML = `<option value="">All FCs</option>` + s.fcs.map((fc) => `<option>${escapeHtml(fc)}</option>`).join("");
  $("run-digest-fcs").innerHTML = s.fcs.map((fc) => `<button class="secondary" data-fc="${escapeHtml(fc)}">Preview ${escapeHtml(fc)}</button>`).join("");
  $("run-digest-fcs").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => previewDigest(b.dataset.fc)));
  if (s.digests && s.digests.length) renderDelivery(s.digests);
  renderTable();
}

function filteredDays() {
  return runState.days.filter((d) => (!runState.fc || d.fc === runState.fc) && (!runState.colour || d.colour === runState.colour));
}

function renderTable() {
  const table = $("run-table");
  $("run-severity").classList.toggle("hidden", runState.tab !== "anomalies");
  const days = filteredDays();

  if (runState.tab === "insights") {
    const flagged = days.filter((d) => d.anomalies.length);
    table.innerHTML = `<tr><th>Date</th><th>FC</th><th>Colour</th><th>Insight</th></tr>` + (flagged.length
      ? flagged.map((d) => `<tr><td class="nowrap">${CS3.dayLabel(d.date)}</td><td>${escapeHtml(d.fc)}</td>
          <td>${CS3.colourBadge(d.colour)}</td><td class="small">${escapeHtml(d.insight)}</td></tr>`).join("")
      : `<tr><td colspan="4" class="muted">No flagged days for these filters.</td></tr>`);
  } else if (runState.tab === "anomalies") {
    const rows = days.flatMap((d) => d.anomalies.map((a) => ({ ...a, colour: d.colour })))
      .filter((a) => !runState.severity || a.severity === runState.severity);
    table.innerHTML = `<tr><th>Date</th><th>FC</th><th>Line item</th><th>% of revenue</th><th>Target range</th>
      <th>Status</th><th>Severity</th><th>Impact</th></tr>` + (rows.length
      ? rows.map((a) => `<tr><td class="nowrap">${CS3.dayLabel(a.day)}</td><td>${escapeHtml(a.fc)}</td><td>${escapeHtml(a.line_item)}</td>
          <td>${CS3.pct(a.pct_of_revenue)}</td><td>${escapeHtml(a.target_range)}</td><td>${escapeHtml(a.status)}${a.acknowledged ? ' <span class="muted small">(known)</span>' : ""}</td>
          <td><span class="sev sev-${a.severity}">${a.severity}</span></td><td>${a.impact_rupees ? rupees(a.impact_rupees) : "-"}</td></tr>`).join("")
      : `<tr><td colspan="8" class="muted">No anomalies for these filters.</td></tr>`);
  } else {
    const lines = ["Manpower", "Packaging", "Power & Fuel", "FC Rent", "Equipment Rentals", "Overheads"];
    table.innerHTML = `<tr><th>Date</th><th>FC</th><th>Revenue</th>${lines.map((l) => `<th>${escapeHtml(l)} %</th>`).join("")}
      <th>CM1</th><th>CM1 %</th><th>CM2</th><th>CM2 %</th><th>Colour</th></tr>` +
      days.map((d) => `<tr><td class="nowrap">${CS3.dayLabel(d.date)}</td><td>${escapeHtml(d.fc)}</td><td>${rupees(d.revenue)}</td>
        ${lines.map((l) => `<td>${CS3.pct(d.pct[l])}</td>`).join("")}
        <td>${rupees(d.cm1)}</td><td>${CS3.pct(d.cm1_pct)}</td><td>${rupees(d.cm2)}</td><td>${CS3.pct(d.cm2_pct)}</td>
        <td>${CS3.colourBadge(d.colour)}</td></tr>`).join("");
  }
}

// ---------------------------------------------------------------- digests

function previewDigest(fc) {
  const frame = $("run-digest-preview");
  frame.classList.remove("hidden");
  frame.src = `/api/cs3/digests/preview?fc=${encodeURIComponent(fc)}`;
}

function renderDelivery(results) {
  $("run-digest-result").innerHTML = `<table class="table compact"><tr><th>FC</th><th>Day</th><th>Channel</th><th>Status</th><th>Detail</th></tr>` +
    results.map((r) => `<tr><td>${escapeHtml(r.fc)}</td><td>${escapeHtml(r.date)}</td><td>${escapeHtml(r.channel)}</td>
      <td>${escapeHtml(r.status)}</td><td class="small">${escapeHtml(r.detail || "")}</td></tr>`).join("") + `</table>`;
}

$("run-send").addEventListener("click", async () => {
  const button = $("run-send");
  button.disabled = true;
  try {
    const fcs = [...new Set(runState.days.map((d) => d.fc))];
    const result = await api("/api/cs3/digests/send", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fcs }),
    });
    renderDelivery(result.results);
  } catch (error) {
    $("run-digest-result").innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  } finally {
    button.disabled = false;
  }
});

// ---------------------------------------------------------------- controls

$("run-tabs").addEventListener("click", (event) => {
  if (!event.target.dataset.tab) return;
  runState.tab = event.target.dataset.tab;
  $("run-tabs").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === event.target));
  renderTable();
});
$("run-fc").addEventListener("change", (e) => { runState.fc = e.target.value; renderTable(); });
$("run-colour").addEventListener("change", (e) => { runState.colour = e.target.value; renderTable(); });
$("run-severity").addEventListener("change", (e) => { runState.severity = e.target.value; renderTable(); });

pollRun();
