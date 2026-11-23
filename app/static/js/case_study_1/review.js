// Case Study 1 review page: flagged frames one at a time. Confirm (with corrections) or keep the flag.

const reviewBatchId = document.getElementById("cs1-review").dataset.batchId;
const el = (id) => document.getElementById(id);
const reviewState = { queue: [], position: 0, total: 0 };
let reviewAction = "confirm";

async function loadQueue() {
  const flagged = await api(`/api/cs1/batches/${reviewBatchId}/records?flagged=true`);
  reviewState.total = flagged.length;
  reviewState.queue = flagged.filter((r) => !r.reviewed);
  reviewState.position = 0;
  showCurrent();
}

async function showCurrent() {
  const done = reviewState.total - reviewState.queue.length;
  if (!reviewState.queue.length) {
    el("review-progress").textContent = `${reviewState.total} flagged frame(s), all reviewed.`;
    el("review-panel").classList.add("hidden");
    el("review-empty").classList.remove("hidden");
    return;
  }
  const summary = reviewState.queue[reviewState.position % reviewState.queue.length];
  const record = await api(`/api/cs1/records/${summary.record_id}`);
  el("review-progress").textContent =
    `${reviewState.queue.length} of ${reviewState.total} flagged frame(s) left to review · ${done} reviewed`;
  el("review-panel").classList.remove("hidden");
  el("review-image").src = `/api/cs1/records/${record.record_id}/image`;
  el("review-image-link").href = `/api/cs1/records/${record.record_id}/image`;
  el("review-file").textContent = `#${record.index} · ${record.filename}`;
  el("review-status").innerHTML = CS1.badge(record.status);
  el("review-reason").textContent = record.status_reason || "";
  el("review-notes").innerHTML = (record.notes || []).map((n) => `<li>${escapeHtml(n)}</li>`).join("");
  const form = el("review-form");
  const seen = CS1.seen(record);
  ["awb", "length_cm", "width_cm", "height_cm", "weight_kg"].forEach((k) => { form.elements[k].value = seen[k]; });
  form.elements.note.value = "";
  form.dataset.recordId = record.record_id;
  el("review-error").textContent = "";
}

el("review-form").addEventListener("click", (event) => {
  if (event.target.dataset.action) reviewAction = event.target.dataset.action;
});

el("review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const value = (k) => form.elements[k].value.trim();
  const numberOrNull = (k) => (value(k) === "" ? null : value(k));   // the API checks it is a number
  const body = { action: reviewAction, awb: value("awb"), note: value("note"),
    length_cm: numberOrNull("length_cm"), width_cm: numberOrNull("width_cm"),
    height_cm: numberOrNull("height_cm"), weight_kg: numberOrNull("weight_kg") };
  try {
    await api(`/api/cs1/records/${form.dataset.recordId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    reviewState.queue.splice(reviewState.position % reviewState.queue.length, 1);
    showCurrent();
  } catch (error) {
    el("review-error").textContent = error.message;
  }
});

el("review-skip").addEventListener("click", () => {
  reviewState.position += 1;
  showCurrent();
});

loadQueue();
