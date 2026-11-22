"""
Background job runner.

The API request only saves the uploads and creates a job document; the heavy
work runs here in a thread pool. Progress is written to MongoDB, so the user
can close the browser and come back - the job page simply reads the job document.

For a production deployment this class is the seam where a real queue
(Celery / RQ / Arq / a cloud task queue) would plug in; the pipeline itself
would not change.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.config import Settings
from app.shared.errors import InputError
from app.case_study_2.pipeline import VerificationPipeline
from app.case_study_2.report import ExcelReportWriter
from app.case_study_2.repository import JobRepository, ResultRepository

log = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, settings: Settings, jobs: JobRepository, results: ResultRepository):
        self.settings = settings
        self.jobs = jobs
        self.results = results
        self.report_writer = ExcelReportWriter()
        self._executor = ThreadPoolExecutor(max_workers=settings.job_workers, thread_name_prefix="verify")

    def submit(self, job_id: str, paths: dict[str, str]) -> None:
        self._executor.submit(self._run, job_id, paths)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ #

    def _run(self, job_id: str, paths: dict[str, str]) -> None:
        def progress(stage: str, percent: int, message: str) -> None:
            self.jobs.update_progress(job_id, stage, percent, message)

        try:
            pipeline = VerificationPipeline(progress=progress)
            report = pipeline.run(paths["wagesheet"], paths["pf_ecr"], paths["esic_ecr"])

            progress("saving", 92, "Saving results")
            self.results.save(job_id, report)

            progress("writing_report", 96, "Writing the Excel report")
            report_path = self.settings.report_dir / f"verification_{job_id}.xlsx"
            self.report_writer.write(report, report_path)

            self.jobs.mark_completed(job_id, report, str(report_path))
            log.info("Job %s completed: %s", job_id, report.summary())

        except InputError as error:
            # Expected, user-fixable problem: show the message as-is.
            log.info("Job %s rejected input: %s", job_id, error.message)
            self.jobs.mark_failed(job_id, error.message)

        except Exception:
            # Unexpected bug: log the full trace, show the user a reference id instead of a stack trace.
            reference = uuid.uuid4().hex[:8]
            log.exception("Job %s failed unexpectedly (ref %s)", job_id, reference)
            self.jobs.mark_failed(
                job_id, f"Something went wrong while processing the files (reference {reference}). "
                        f"Please try again or share the reference with the support team.")


def save_upload(upload_dir: Path, job_id: str, slot: str, filename: str, content: bytes) -> str:
    """Store an uploaded file as storage/uploads/<job_id>/<slot><ext> and return its path."""
    folder = upload_dir / job_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slot}{Path(filename).suffix.lower()}"
    path.write_bytes(content)
    return str(path)
