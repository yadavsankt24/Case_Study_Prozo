// Case Study 1 helpers shared by the batch and review pages.

const CS1 = {
  // same order as rules.STATUS_PRIORITY, OK last
  STATUSES: ["OK", "NEEDS_REVIEW", "PARCEL_PARTIAL", "MULTIPLE_PARCELS", "NO_PARCEL", "VIEW_OBSTRUCTED",
             "UNREADABLE", "PROCESSING_ERROR", "INVALID_IMAGE"],

  LABELS: {
    OK: "OK", NEEDS_REVIEW: "Needs review", PARCEL_PARTIAL: "Parcel partial", MULTIPLE_PARCELS: "Multiple parcels",
    NO_PARCEL: "No parcel", VIEW_OBSTRUCTED: "View obstructed", UNREADABLE: "Unreadable",
    PROCESSING_ERROR: "Processing error", INVALID_IMAGE: "Invalid image",
  },

  badge(status) {
    if (!status) return `<span class="cs1-badge st-pending">reading…</span>`;
    return `<span class="cs1-badge st-${status}" title="${escapeHtml(status)}">${escapeHtml(CS1.LABELS[status] || status)}</span>`;
  },

  num(value, digits = 2) {
    return value === null || value === undefined || value === "" ? "-" : Number(value).toLocaleString("en-IN", { maximumFractionDigits: digits });
  },

  dims(r) {
    return r.length_cm ? `${CS1.num(r.length_cm)} × ${CS1.num(r.width_cm)} × ${CS1.num(r.height_cm)}` : "-";
  },

  /** Values the readers saw, used to pre-fill the review form (clean columns are blank on flagged frames). */
  seen(r) {
    const ocr = (r.readers && r.readers.ocr) || {};
    const dims = ocr.dimensions || [r.length_cm, r.width_cm, r.height_cm];
    return {
      awb: r.awb || ocr.awb || (r.label_barcodes || [])[0] || "",
      length_cm: dims[0] ?? "", width_cm: dims[1] ?? "", height_cm: dims[2] ?? "",
      weight_kg: r.weight_kg ?? ocr.weight_kg ?? "",
    };
  },

  detailHtml(r) {
    const row = (label, value) => `<tr><th>${label}</th><td>${value}</td></tr>`;
    const vision = r.readers && r.readers.vision;
    const visionHtml = vision
      ? `parcels ${vision.parcel_count} · cut off ${vision.parcel_cut_off ? "yes" : "no"} · obstructed ${vision.view_obstructed ? "yes" : "no"}
         · overlay AWB ${escapeHtml(vision.overlay_awb || "-")} · label AWB ${escapeHtml(vision.label_awb || "-")}
         · dims "${escapeHtml(vision.overlay_dimensions_text || "-")}" · weight "${escapeHtml(vision.overlay_weight_text || "-")}"`
      : escapeHtml((r.readers && r.readers.vision_error) || "not used (offline mode)");
    const ocrRows = (r.readers && r.readers.ocr && r.readers.ocr.rows) || [];
    return `
      <div class="row-between"><h2>${escapeHtml(r.filename)}</h2>
        <div class="button-row"><button class="secondary" id="detail-rerun" data-id="${r.record_id}">Re-read this frame</button>
        <button class="secondary" id="detail-close">Close</button></div></div>
      <div class="cs1-detail">
        <a href="/api/cs1/records/${r.record_id}/image" target="_blank"><img src="/api/cs1/records/${r.record_id}/image" alt="Frame"></a>
        <div>
          <p>${CS1.badge(r.status)} <span class="small">${escapeHtml(r.status_reason || "")}</span></p>
          <table class="table compact cs1-kv">
            ${row("AWB", escapeHtml(r.awb || "-"))}
            ${row("L × W × H (cm)", CS1.dims(r))}
            ${row("Weight (kg)", CS1.num(r.weight_kg, 3))}
            ${row("Volume (cm³)", CS1.num(r.volume_cm3, 1))}
            ${row("Confidence", escapeHtml(r.confidence || "-") + (r.reviewed ? " · reviewed" : ""))}
            ${row("Location · time · machine", [r.location, r.scan_time, r.machine_id].map((v) => escapeHtml(v || "-")).join(" · "))}
            ${row("AWB as read", escapeHtml(r.awb_as_read || "-"))}
            ${row("Dimensions as read", escapeHtml(r.dimensions_as_read || "-"))}
            ${row("Weight as read", escapeHtml(r.weight_as_read || "-"))}
            ${row("Label barcodes", escapeHtml((r.label_barcodes || []).join(", ") || "none decoded"))}
            ${row("Vision agent", visionHtml)}
          </table>
          ${(r.notes || []).length ? `<ul class="small">${r.notes.map((n) => `<li>${escapeHtml(n)}</li>`).join("")}</ul>` : ""}
          <details class="small"><summary>Overlay text read by OCR (${ocrRows.length} rows)</summary>
            <pre class="cs1-pre">${escapeHtml(ocrRows.join("\n") || "(none)")}</pre></details>
        </div>
      </div>`;
  },
};
