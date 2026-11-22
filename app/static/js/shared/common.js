// Small helpers shared by all pages.

/** Escape text before inserting it into HTML. */
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

/** Format a number as Indian rupees, or "-" when empty. */
function rupees(value) {
  if (value === null || value === undefined) return "-";
  const amount = Math.abs(Number(value)).toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return (Number(value) < 0 ? "−₹" : "₹") + amount;
}

/** CSS class for a status, e.g. "Name mismatch" -> "s-Name-mismatch". */
function statusClass(status) {
  return "s-" + String(status || "").replace(/\s+/g, "-");
}

function statusBadge(status) {
  return `<span class="badge ${statusClass(status)}">${escapeHtml(status)}</span>`;
}

/** fetch() wrapper that turns API errors into readable messages. */
async function api(url, options = {}) {
  const response = await fetch(url, options);
  let body = null;
  try { body = await response.json(); } catch { /* non-JSON response */ }
  if (!response.ok) {
    const detail = body && body.detail;
    const message = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail;
    throw new Error(message || `Request failed (${response.status})`);
  }
  return body;
}
