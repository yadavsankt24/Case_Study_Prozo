// Case Study 1 batch page: progress, counts per status, table / thumbnails, frame detail.

const batchId = document.getElementById("cs1-batch").dataset.batchId;
const $ = (id) => document.getElementById(id);
const batchState = { view: "table", status: "", search: "", records: [], failures: 0 };
const MAX_POLL_FAILURES = 10;   // temporary server / database errors are retried before giving up

// ---------------------------------------------------------------- progress

async function pollBatch() {
  let batch;
  try {
    batch = await api(`/api/cs1/batches/${batchId}`);
    batchState.failures = 0;
  } catch (error) {
    batchState.failures += 1;
    if (error.message === "Batch not found." || batchState.failures >= MAX_POLL_FAILURES) return showBatchError(error.message);
    $("batch-message").textContent = `Connection problem (${error.message}) - retrying…`;
    return setTimeout(pollBatch, 2000 * batchState.failures);
  }
  const s = batch.summary;
  $("batch-title").textContent = `Batch · ${batch.label}`;
  $("batch-status").textContent = batch.status;
  $("batch-status").className = `pill ${batch.status}`;
  $("batch-mode").textContent = batch.vision_enabled
    ? `Vision agent on (${batch.vision_model}): scene check + second read for every frame.`
    : "Offline mode: OCR + barcode only; the scene (cut off, two parcels, covered) was not checked.";
  $("batch-progress").style.width = `${batch.total ? (100 * s.done) / batch.total : 0}%`;
  $("batch-message").textContent = batch.status === "completed"
    ? batch.message : `${s.done} of ${batch.total} frames read · ${s.ok} OK · ${s.flagged} flagged`;

  if (batch.status === "failed") return showBatchError(batch.error || batch.message);
  try {
    if (s.done) await showResults(batch);
  } catch (error) {
    $("batch-message").textContent = `Connection problem (${error.message}) - retrying…`;
    return setTimeout(pollBatch, 3000);
  }
  if (batch.status !== "completed") setTimeout(pollBatch, 1500);
}

function showBatchError(message) {
  $("batch-error").classList.remove("hidden");
  $("batch-error-text").textContent = message;
}

// ---------------------------------------------------------------- results

async function showResults(batch) {
  $("batch-results").classList.remove("hidden");
  $("batch-csv").href = `/api/cs1/batches/${batchId}/csv`;
  $("batch-review").href = `/case-study-1/batches/${batchId}/review`;
  const s = batch.summary;

  const tile = (label, value, cls = "") => `<div class="cs1-tile ${cls}"><b>${value}</b><span>${label}</span></div>`;
  $("batch-tiles").innerHTML = tile("Frames", batch.total) + tile("Read OK", s.ok, "st-OK") +
    tile("Flagged", s.flagged, s.flagged ? "st-NEEDS_REVIEW" : "") + tile("Read automatically", `${s.auto_read_pct}%`) +
    tile("Reviewed", s.reviewed);

  $("batch-statuses").innerHTML = CS1.STATUSES.filter((st) => s.counts[st]).map((st) =>
    `<button class="cs1-chip ${batchState.status === st ? "active" : ""}" data-status="${st}">${CS1.badge(st)} <b>${s.counts[st]}</b></button>`).join("");
  $("batch-statuses").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => setStatus(b.dataset.status)));

  $("batch-filter").innerHTML = `<option value="">All statuses</option>` +
    CS1.STATUSES.filter((st) => s.counts[st]).map((st) => `<option value="${st}">${CS1.LABELS[st]} (${s.counts[st]})</option>`).join("");
  $("batch-filter").value = batchState.status;

  $("batch-rerun").classList.toggle("hidden", !s.counts.PROCESSING_ERROR);
  $("batch-review").classList.toggle("hidden", !s.flagged);
  $("batch-skipped").innerHTML = (batch.skipped || []).length
    ? `<div class="warning">Skipped (not images): ${batch.skipped.map(escapeHtml).join(", ")}</div>` : "";

  batchState.records = await api(`/api/cs1/batches/${batchId}/records`);
  render();
}

function visibleRecords() {
  const q = batchState.search.toLowerCase();
  return batchState.records.filter((r) => (!batchState.status || r.status === batchState.status) &&
    (!q || [r.filename, r.awb, r.awb_as_read, r.location].some((v) => String(v || "").toLowerCase().includes(q))));
}

function render() {
  const records = visibleRecords();
  $("batch-table-wrap").classList.toggle("hidden", batchState.view !== "table");
  $("batch-grid").classList.toggle("hidden", batchState.view !== "grid");

  if (batchState.view === "table") {
    $("batch-table").innerHTML = `<tr><th>#</th><th>Frame</th><th>Status</th><th>AWB</th><th>L × W × H (cm)</th>
      <th>Weight (kg)</th><th>Confidence</th><th class="cs1-reason">Reason</th></tr>` + (records.length ? records.map((r) => `
      <tr class="clickable" data-id="${r.record_id}">
        <td>${r.index}</td><td>${escapeHtml(r.filename)}</td><td>${CS1.badge(r.status)}${r.reviewed ? ' <span class="muted small">reviewed</span>' : ""}</td>
        <td class="nowrap">${escapeHtml(r.awb || "-")}</td><td class="nowrap">${CS1.dims(r)}</td><td>${CS1.num(r.weight_kg, 3)}</td>
        <td>${escapeHtml(r.confidence || "-")}</td>
        <td class="small">${escapeHtml(r.status_reason || "")}${(r.notes || []).length ? ` <span class="muted" title="${escapeHtml(r.notes.join("\n"))}">(${r.notes.length} note${r.notes.length > 1 ? "s" : ""})</span>` : ""}</td>
      </tr>`).join("") : `<tr><td colspan="8" class="muted">No frames for these filters.</td></tr>`);
    $("batch-table").querySelectorAll("tr[data-id]").forEach((tr) => tr.addEventListener("click", () => openDetail(tr.dataset.id)));
  } else {
    $("batch-grid").innerHTML = records.length ? records.map((r) => `
      <figure class="cs1-thumb" data-id="${r.record_id}">
        ${r.done ? `<img loading="lazy" src="/api/cs1/records/${r.record_id}/thumbnail" alt="">` : `<div class="cs1-thumb-wait">reading…</div>`}
        <figcaption>${CS1.badge(r.status)}<span class="small">${escapeHtml(r.awb || r.filename)}</span></figcaption>
      </figure>`).join("") : `<p class="muted">No frames for these filters.</p>`;
    $("batch-grid").querySelectorAll("figure").forEach((f) => f.addEventListener("click", () => openDetail(f.dataset.id)));
  }
}

async function openDetail(recordId) {
  const record = await api(`/api/cs1/records/${recordId}`);
  const panel = $("frame-detail");
  panel.classList.remove("hidden");
  panel.innerHTML = CS1.detailHtml(record);
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
  $("detail-close").addEventListener("click", () => panel.classList.add("hidden"));
  $("detail-rerun").addEventListener("click", async (event) => {
    event.target.disabled = true;
    await api(`/api/cs1/records/${recordId}/rerun`, { method: "POST" });
    panel.classList.add("hidden");
    pollBatch();
  });
}

function setStatus(status) {
  batchState.status = batchState.status === status ? "" : status;
  $("batch-filter").value = batchState.status;
  $("batch-statuses").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.status === batchState.status));
  render();
}

// ---------------------------------------------------------------- controls

$("batch-view").addEventListener("click", (event) => {
  if (!event.target.dataset.view) return;
  batchState.view = event.target.dataset.view;
  $("batch-view").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === event.target));
  render();
});
$("batch-filter").addEventListener("change", (e) => setStatus(e.target.value || batchState.status));
$("batch-search").addEventListener("input", (e) => { batchState.search = e.target.value; render(); });
$("batch-rerun").addEventListener("click", async (event) => {
  event.target.disabled = true;
  await api(`/api/cs1/batches/${batchId}/rerun`, { method: "POST" });
  event.target.disabled = false;
  pollBatch();
});

pollBatch();
