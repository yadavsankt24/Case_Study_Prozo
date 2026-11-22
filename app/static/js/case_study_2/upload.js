// Case Study 2 upload page: upload the three files and list recent jobs.

const form = document.getElementById("upload-form");
const submitButton = document.getElementById("submit-btn");
const formError = document.getElementById("form-error");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.textContent = "";

  const missing = ["wagesheet", "pf_ecr", "esic_ecr"].filter((name) => !form.elements[name].files.length);
  if (missing.length) {
    formError.textContent = "Please choose all three files before starting.";
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = "Uploading...";
  try {
    const job = await api("/api/jobs", { method: "POST", body: new FormData(form) });
    window.location.href = `/case-study-2/jobs/${job.job_id}`;
  } catch (error) {
    formError.textContent = error.message;
    submitButton.disabled = false;
    submitButton.textContent = "Start verification";
  }
});

async function loadRecentJobs() {
  const tbody = document.querySelector("#jobs-table tbody");
  try {
    const jobs = await api("/api/jobs?limit=15");
    if (!jobs.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="muted">No verifications yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = jobs.map((job) => {
      const pf = job.summary ? `${job.summary.pf.counts.Matched}/${job.summary.pf.total}` : "-";
      const esic = job.summary ? `${job.summary.esic.counts.Matched}/${job.summary.esic.total}` : "-";
      const title = job.label || job.input_files.wagesheet;
      return `<tr>
        <td>${new Date(job.created_at).toLocaleString()}</td>
        <td>${escapeHtml(title)}</td>
        <td><span class="pill ${job.status}">${escapeHtml(job.status)}</span></td>
        <td>${pf}</td><td>${esic}</td>
        <td><a href="/case-study-2/jobs/${job.job_id}">Open</a></td>
      </tr>`;
    }).join("");
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="6" class="error">${escapeHtml(error.message)}</td></tr>`;
  }
}

loadRecentJobs();
