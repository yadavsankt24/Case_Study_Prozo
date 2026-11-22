// Case Study 3 shared helpers: the FC x date colour grid and small formatters.

const CS3 = {
  pct: (v) => (v === null || v === undefined ? "-" : `${Number(v).toFixed(1)}%`),

  dayLabel: (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short" }),

  colourBadge: (colour) => `<span class="cs3-badge c-${colour}">${escapeHtml(colour)}</span>`,

  /**
   * Render a grid: one row per FC, one cell per date, coloured by status.
   * cells: [{fc, date, colour, cm2_pct, insight, ...}]
   * onSelect(cell) is called when a cell is clicked.
   */
  renderGrid(container, cells, onSelect) {
    const fcs = [...new Set(cells.map((c) => c.fc))].sort();
    const dates = [...new Set(cells.map((c) => c.date))].sort();
    const byKey = new Map(cells.map((c) => [`${c.fc}|${c.date}`, c]));

    const head = `<tr><th class="sticky-col">FC</th>${dates.map((d) => `<th class="cs3-date">${CS3.dayLabel(d)}</th>`).join("")}</tr>`;
    const body = fcs.map((fc) => `<tr><th class="sticky-col">${escapeHtml(fc)}</th>${dates.map((d) => {
      const cell = byKey.get(`${fc}|${d}`);
      if (!cell) return `<td class="cs3-cell empty"></td>`;
      return `<td class="cs3-cell c-${cell.colour}" data-key="${escapeHtml(fc)}|${d}"
                 title="${escapeHtml(fc)} ${d}: CM2 ${CS3.pct(cell.cm2_pct)} (${cell.colour})">${Math.round(cell.cm2_pct)}</td>`;
    }).join("")}</tr>`).join("");

    container.innerHTML = `<table class="cs3-grid">${head}${body}</table>`;
    container.querySelectorAll("td[data-key]").forEach((td) => td.addEventListener("click", () => {
      container.querySelectorAll("td.selected").forEach((s) => s.classList.remove("selected"));
      td.classList.add("selected");
      onSelect(byKey.get(td.dataset.key));
    }));
  },

  detailHtml(cell) {
    return `<div class="row-between"><b>${escapeHtml(cell.fc)} · ${CS3.dayLabel(cell.date)}</b>${CS3.colourBadge(cell.colour)}</div>
            <p>${escapeHtml(cell.insight || "")}</p>`;
  },
};
