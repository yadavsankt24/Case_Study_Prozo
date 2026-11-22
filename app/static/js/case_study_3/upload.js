// Case Study 3 upload page: submit the file and list recent analyses.

const cs3Form = document.getElementById("cs3-form");
const cs3Submit = document.getElementById("cs3-submit");
const cs3Error = document.getElementById("cs3-error");

cs3Form.addEventListener("submit", async (event) => {
  event.preventDefault();
  cs3Error.textContent = "";
  if (!cs3Form.elements.data_file.files.length) {
    cs3Error.textContent = "Please choose a file first.";
    return;
  }
  cs3Submit.disabled = true;
  cs3Submit.textContent = "Uploading...";
  try {
    const run = await api("/api/cs3/runs", { method: "POST", body: new FormData(cs3Form) });
    window.location.href = `/case-study-3/runs/${run.run_id}`;
  } catch (error) {
    cs3Error.textContent = error.message;
    cs3Submit.disabled = false;
    cs3Submit.textContent = "Analyse";
  }
});

async function loadRuns() {
  const tbody = document.querySelector("#cs3-runs tbody");
  try {
    const runs = await api("/api/cs3/runs?limit=15");
    if (!runs.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="muted">No analyses yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = runs.map((run) => {
      const s = run.summary;
      const colours = s ? `${s.colours.Red} / ${s.colours.Yellow} / ${s.colours.Green} / ${s.colours.Blue}` : "-";
      return `<tr>
        <td>${new Date(run.created_at).toLocaleString()}</td>
        <td>${escapeHtml(run.filename)}</td>
        <td><span class="pill ${run.status}">${escapeHtml(run.status)}</span></td>
        <td>${s ? s.fcs.length : "-"}</td><td>${s ? s.fc_days : "-"}</td><td>${colours}</td>
        <td class="nowrap"><a href="/case-study-3/runs/${run.run_id}">Open</a>
          <button class="btn-delete" data-run-id="${run.run_id}" data-name="${escapeHtml(run.filename)}">Delete</button></td>
      </tr>`;
    }).join("");
    tbody.querySelectorAll(".btn-delete").forEach((button) => button.addEventListener("click", () => deleteRun(button)));
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="7" class="error">${escapeHtml(error.message)}</td></tr>`;
  }
}

async function deleteRun(button) {
  const ok = confirm(`Delete the analysis of "${button.dataset.name}"?\n\n` +
    "This removes its results, report and the daily data it added to the dashboard. This cannot be undone.");
  if (!ok) return;
  button.disabled = true;
  try {
    await api(`/api/cs3/runs/${button.dataset.runId}`, { method: "DELETE" });
    loadRuns();
  } catch (error) {
    button.disabled = false;
    cs3Error.textContent = error.message;
  }
}

loadRuns();
