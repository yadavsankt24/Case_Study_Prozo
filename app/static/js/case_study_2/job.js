// Case Study 2 job page: poll progress, then show summary, results table and the Ask box.

const jobId = document.getElementById("app").dataset.jobId;
const POLL_MS = 1500;

const state = { tab: "combined", status: "", needsReview: false, search: "", page: 1, pageSize: 50 };
const el = (id) => document.getElementById(id);

// ---------------------------------------------------------------- progress

async function pollJob() {
  let job;
  try {
    job = await api(`/api/jobs/${jobId}`);
  } catch (error) {
    showError(error.message);
    return;
  }
  renderProgress(job);
  if (job.status === "completed") {
    showResults(job);
  } else if (job.status === "failed") {
    showError(job.error || job.message);
  } else {
    setTimeout(pollJob, POLL_MS);
  }
}

function renderProgress(job) {
  el("job-title").textContent = job.label || "Verification";
  el("job-files").textContent =
    `${job.input_files.wagesheet} · ${job.input_files.pf_ecr} · ${job.input_files.esic_ecr}`;
  el("job-status").textContent = job.status;
  el("job-status").className = `pill ${job.status}`;
  el("progress-bar").style.width = `${job.progress || 0}%`;
  el("progress-message").textContent = job.message || "";
}

function showError(message) {
  el("error-card").classList.remove("hidden");
  el("error-message").textContent = message;
}

// ---------------------------------------------------------------- results

function showResults(job) {
  el("results").classList.remove("hidden");
  el("download-btn").href = `/api/jobs/${jobId}/report`;
  renderSummary(job.summary);
  renderWarnings(job.warnings || []);
  renderReconciliation(job.reconciliation || []);
  loadTable();
}

function renderSummary(summary) {
  const box = (check, label) => {
    const data = summary[check];
    const stats = Object.entries(data.counts).map(([status, count]) =>
      `<div class="stat ${statusClass(status)}" data-check="${check}" data-status="${escapeHtml(status)}">
         <b>${count}</b><span>${escapeHtml(status)}</span></div>`).join("");
    return `<div class="summary-box">
      <h3>${label} · ${data.match_rate}% matched</h3>
      <div class="stats">${stats}</div>
      <p class="small muted">Needs review: ${data.needs_review} · Short-deposited: ${rupees(data.short_deposit_amount)}
         · In ECR but not in wagesheet: ${summary.ecr_only[check]}</p>
    </div>`;
  };
  el("summary").innerHTML = box("pf", "PF") + box("esic", "ESIC");

  // Clicking a count jumps to that list.
  el("summary").querySelectorAll(".stat").forEach((stat) => stat.addEventListener("click", () => {
    selectTab(stat.dataset.check);
    state.status = stat.dataset.status;
    el("status-filter").value = state.status;
    loadTable();
  }));
}

function renderWarnings(warnings) {
  el("warnings").innerHTML = warnings.map((w) => `<div class="warning">${escapeHtml(w)}</div>`).join("");
}

function renderReconciliation(checks) {
  el("reconciliation").innerHTML = `<tr><th>Document</th><th>Metric</th><th>Printed</th><th>Parsed</th><th>Result</th></tr>` +
    checks.map((c) => `<tr><td>${escapeHtml(c.document)}</td><td>${escapeHtml(c.metric)}</td>
      <td>${c.printed_value ?? "-"}</td><td>${c.parsed_value}</td>
      <td>${c.ok ? "OK" : "⚠ " + escapeHtml(c.note)}</td></tr>`).join("");
}

async function loadTable() {
  const table = el("results-table");
  el("filters").classList.toggle("hidden", state.tab === "ecr-only");

  if (state.tab === "ecr-only") {
    const members = await api(`/api/jobs/${jobId}/ecr-only`);
    table.innerHTML = `<tr><th>ECR</th><th>Identifier</th><th>Name in ECR</th><th>Amount</th><th>Page</th></tr>` +
      (members.length ? members.map((m) => `<tr><td>${m.check}</td><td>${m.identifier}</td>
        <td>${escapeHtml(m.name)}</td><td>${rupees(m.amount)}</td><td>${m.page}</td></tr>`).join("")
        : `<tr><td colspan="5" class="muted">Every ECR member is on the wagesheet.</td></tr>`);
    el("pager").innerHTML = "";
    return;
  }

  const params = new URLSearchParams({ page: state.page, page_size: state.pageSize });
  if (state.tab !== "combined") params.set("check", state.tab);
  if (state.status) params.set("status", state.status);
  if (state.needsReview) params.set("needs_review", "true");
  if (state.search) params.set("q", state.search);

  const data = await api(`/api/jobs/${jobId}/results?${params}`);
  table.innerHTML = state.tab === "combined" ? combinedRows(data.items) : checkRows(data.items, state.tab);
  renderPager(data.total);
}

function combinedRows(items) {
  const header = `<tr><th>Row</th><th>Name</th><th>UAN</th><th>IP Number</th><th>PF</th><th>ESIC</th><th>Reasons</th></tr>`;
  if (!items.length) return header + `<tr><td colspan="7" class="muted">No employees match these filters.</td></tr>`;
  return header + items.map((e) => `<tr>
    <td>${e.row_number}</td><td>${escapeHtml(e.name)}</td><td>${e.uan || "-"}</td><td>${e.ip_number || "-"}</td>
    <td>${statusBadge(e.pf.status)}${reviewTag(e.pf)}</td><td>${statusBadge(e.esic.status)}${reviewTag(e.esic)}</td>
    <td class="small"><b>PF:</b> ${escapeHtml(e.pf.reason)}<br><b>ESIC:</b> ${escapeHtml(e.esic.reason)}</td>
  </tr>`).join("");
}

function checkRows(items, check) {
  const idLabel = check === "pf" ? "UAN" : "IP Number";
  const header = `<tr><th>Row</th><th>Name</th><th>${idLabel}</th><th>ECR name</th><th>Wagesheet</th>
    <th>ECR</th><th>Difference</th><th>Status</th><th>Reason</th></tr>`;
  if (!items.length) return header + `<tr><td colspan="9" class="muted">No employees match these filters.</td></tr>`;
  return header + items.map((e) => {
    const r = e[check];
    return `<tr>
      <td>${e.row_number}</td><td>${escapeHtml(e.name)}</td><td>${r.identifier || "-"}</td>
      <td>${escapeHtml(r.ecr_name || "-")}</td><td>${rupees(r.wagesheet_amount)}</td><td>${rupees(r.ecr_amount)}</td>
      <td>${r.difference === null ? "-" : rupees(r.difference)}</td>
      <td>${statusBadge(r.status)}${reviewTag(r)}</td><td class="small">${escapeHtml(r.reason)}</td>
    </tr>`;
  }).join("");
}

function reviewTag(result) {
  return result.needs_review ? `<div class="review">needs review</div>` : "";
}

function renderPager(total) {
  const pages = Math.max(1, Math.ceil(total / state.pageSize));
  el("pager").innerHTML = `<span class="muted small">${total} employee(s)</span>
    <button ${state.page <= 1 ? "disabled" : ""} data-page="${state.page - 1}">Previous</button>
    <span class="small">Page ${state.page} of ${pages}</span>
    <button ${state.page >= pages ? "disabled" : ""} data-page="${state.page + 1}">Next</button>`;
  el("pager").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    state.page = Number(b.dataset.page);
    loadTable();
  }));
}

// ---------------------------------------------------------------- controls

function selectTab(tab) {
  state.tab = tab;
  state.page = 1;
  el("tabs").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
}

el("tabs").addEventListener("click", (event) => {
  if (!event.target.dataset.tab) return;
  selectTab(event.target.dataset.tab);
  loadTable();
});
el("status-filter").addEventListener("change", (e) => { state.status = e.target.value; state.page = 1; loadTable(); });
el("review-filter").addEventListener("change", (e) => { state.needsReview = e.target.checked; state.page = 1; loadTable(); });

let searchTimer;
el("search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.search = e.target.value; state.page = 1; loadTable(); }, 300);
});

// ---------------------------------------------------------------- ask

el("ask-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const answerBox = el("answer");
  answerBox.classList.remove("hidden");
  answerBox.textContent = "Thinking...";
  try {
    const result = await api(`/api/jobs/${jobId}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: el("question").value }),
    });
    const sources = result.sources.length ? ` · sources: ${result.sources.join(", ")}` : "";
    answerBox.innerHTML = `${escapeHtml(result.answer).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")}
      <div class="meta">answered by: ${escapeHtml(result.mode)}${escapeHtml(sources)}</div>`;
  } catch (error) {
    answerBox.textContent = error.message;
  }
});

pollJob();
