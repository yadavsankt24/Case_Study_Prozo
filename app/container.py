"""
Composition root: builds every long-lived object once and wires them together.

Routes receive the container through FastAPI dependencies, which keeps them
thin and makes tests easy (build a container with an in-memory DB).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request

from app.case_study_1.repository import Cs1Repository
from app.case_study_1.service import Cs1Service
from app.case_study_1.vision import create_vision_reader
from app.case_study_2.assistant.assistant import ComplianceAssistant
from app.case_study_2.job_runner import JobRunner
from app.case_study_2.repository import JobRepository, ResultRepository
from app.case_study_3.repository import Cs3Repository
from app.case_study_3.scheduler import DailyDigestScheduler, create_scheduler
from app.case_study_3.service import Cs3Service
from app.config import Settings
from app.shared.db import connect
from app.shared.llm import create_llm_client


@dataclass
class Container:
    settings: Settings
    in_memory_db: bool
    # Case Study 1
    cs1_repo: Cs1Repository
    cs1: Cs1Service
    # Case Study 2
    jobs: JobRepository
    results: ResultRepository
    runner: JobRunner
    assistant: ComplianceAssistant
    # Case Study 3
    cs3_repo: Cs3Repository
    cs3: Cs3Service
    cs3_scheduler: Optional[DailyDigestScheduler]

    @classmethod
    def build(cls, settings: Settings) -> "Container":
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        settings.report_dir.mkdir(parents=True, exist_ok=True)

        handle = connect(settings)
        jobs = JobRepository(handle.db)
        results = ResultRepository(handle.db)
        llm = create_llm_client(settings)
        cs1_repo = Cs1Repository(handle.db)
        vision = create_vision_reader(settings.gemini_api_key, settings.cs1_vision_model,
                                      settings.cs1_use_vision, settings.cs1_vision_per_minute)
        cs3_repo = Cs3Repository(handle.db)
        cs3 = Cs3Service(settings, cs3_repo, llm=llm)
        return cls(
            settings=settings,
            jobs=jobs,
            results=results,
            runner=JobRunner(settings, jobs, results),
            assistant=ComplianceAssistant(jobs, results, llm=llm),
            in_memory_db=handle.in_memory,
            cs1_repo=cs1_repo,
            cs1=Cs1Service(settings, cs1_repo, vision=vision),
            cs3_repo=cs3_repo,
            cs3=cs3,
            cs3_scheduler=create_scheduler(cs3, settings.cs3_digest_time),
        )


def get_container(request: Request) -> Container:
    return request.app.state.container
