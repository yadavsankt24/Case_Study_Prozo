// Case Study 1 upload page: send the frames / ZIPs and list recent batches.

const cs1Form = document.getElementById("cs1-form");
const cs1Submit = document.getElementById("cs1-submit");
const cs1Error = document.getElementById("cs1-error");
const cs1Files = cs1Form.elements.files;

cs1Files.addEventListener("change", () => {
  const files = [...cs1Files.files];
  const mb = files.reduce((sum, f) => sum + f.size, 0) / 1024 / 1024;
  document.getElementById("cs1-picked").textContent = files.length
    ? `${files.length} file(s) selected · ${mb.toFixed(1)} MB` : "";
});

cs1Form.addEventListener("submit", async (event) => {
  event.preventDefault();
  cs1Error.textContent = "";
  if (!cs1Files.files.length) {
    cs1Error.textContent = "Please choose at least one frame or ZIP file.";
    return;
  }
  cs1Submit.disabled = true;
  cs1Submit.textContent = "Uploading...";
  try {
    const batch = await api("/api/cs1/batches", { method: "POST", body: new FormData(cs1Form) });
    window.location.href = `/case-study-1/batches/${batch.batch_id}`;
  } catch (error) {
    cs1Error.textContent = error.message;
    cs1Submit.disabled = false;
    cs1Submit.textContent = "Read frames";
  }
});

async function loadBatches() {
  const tbody = document.querySelector("#cs1-batches tbody");
  try {
    const batches = await api("/api/cs1/batches?limit=15");
    if (!batches.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="muted">No batches yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = batches.map((b) => {
      const s = b.summary;
      return `<tr>
        <td>${new Date(b.created_at).toLocaleString()}</td>
        <td>${escapeHtml(b.label)}</td>
        <td><span class="pill ${b.status}">${escapeHtml(b.status)}</span></td>
        <td>${s.done} / ${b.total}</td><td>${s.ok}</td><td>${s.flagged}</td><td>${s.done ? s.auto_read_pct + "%" : "-"}</td>
        <td class="small">${b.vision_enabled ? "vision" : "offline"}</td>
        <td class="nowrap"><a href="/case-study-1/batches/${b.batch_id}">Open</a>
          <button class="btn-delete" data-id="${b.batch_id}" data-name="${escapeHtml(b.label)}">Delete</button></td>
      </tr>`;
    }).join("");
    tbody.querySelectorAll(".btn-delete").forEach((button) => button.addEventListener("click", () => deleteBatch(button)));
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="9" class="error">${escapeHtml(error.message)}</td></tr>`;
  }
}

async function deleteBatch(button) {
  const ok = confirm(`Delete the batch "${button.dataset.name}"?\n\nThis removes its frames, results and reviews. This cannot be undone.`);
  if (!ok) return;
  button.disabled = true;
  try {
    await api(`/api/cs1/batches/${button.dataset.id}`, { method: "DELETE" });
    loadBatches();
  } catch (error) {
    button.disabled = false;
    cs1Error.textContent = error.message;
  }
}

loadBatches();
