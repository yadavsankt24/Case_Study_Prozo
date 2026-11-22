"""
Daily digest scheduler: "watches the numbers" without anyone pressing a button.

At CS3_DIGEST_TIME (e.g. "20:30") every day it sends each FC's digest for its
latest stored day, skipping FCs whose digest for that day was already sent.
A plain background thread keeps it dependency-free and easy to read; in
production this would be a cron job / cloud scheduler calling the same method.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Optional

from app.case_study_3.service import Cs3Service

log = logging.getLogger(__name__)
CHECK_EVERY_SECONDS = 30


class DailyDigestScheduler:
    def __init__(self, service: Cs3Service, at: str):
        self.service = service
        self.hour, self.minute = (int(part) for part in at.split(":"))
        self._stop = threading.Event()
        self._last_run_date: Optional[str] = None
        self._thread = threading.Thread(target=self._loop, name="cs3-digest-scheduler", daemon=True)

    def start(self) -> None:
        log.info("CS3 daily digest scheduled at %02d:%02d", self.hour, self.minute)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(CHECK_EVERY_SECONDS):
            now = datetime.now()
            today = now.date().isoformat()
            due = (now.hour, now.minute) >= (self.hour, self.minute)
            if due and self._last_run_date != today:
                self._last_run_date = today
                try:
                    records = self.service.send_digests(skip_already_sent=True)
                    log.info("Scheduled CS3 digests: %d sent/saved", len(records))
                except Exception:
                    log.exception("Scheduled CS3 digest run failed")


def create_scheduler(service: Cs3Service, at: str) -> Optional[DailyDigestScheduler]:
    if not at:
        return None
    try:
        return DailyDigestScheduler(service, at)
    except ValueError:
        log.warning("CS3_DIGEST_TIME '%s' is not HH:MM - daily digests disabled", at)
        return None
