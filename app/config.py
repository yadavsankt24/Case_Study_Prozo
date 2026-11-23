"""
Application settings (infrastructure only).

Business rules live with each case study - `app/case_study_1/rules.py` (flags, overlay
keys, units), `app/case_study_2/rules.py` (rates, tolerance, column aliases) and
`app/case_study_3/rules.py` (targets, colours, severity) - so business logic and
deployment settings never get mixed up.

Every setting can be overridden with an environment variable (see `.env.example`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_dotenv() -> None:
    """Read PROJECT_ROOT/.env if present. Real environment variables always win."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv not installed: rely on the shell environment
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    # --- MongoDB -------------------------------------------------------------
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "prozo_compliance"
    # When MongoDB is not reachable, fall back to an in-memory mock so the
    # app still runs for a quick demo (data is lost on restart).
    allow_in_memory_db: bool = True
    force_in_memory_db: bool = False

    # --- File storage --------------------------------------------------------
    storage_dir: Path = PROJECT_ROOT / "storage"
    max_upload_mb: int = 50

    # --- Background jobs -----------------------------------------------------
    job_workers: int = 2

    # --- Optional AI assistant -----------------------------------------------
    # "none" (default, rule-based answers), "gemini" (free tier key) or "ollama" (local).
    llm_provider: str = "none"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    # --- Case Study 1: parcel frames -> shipment data -----------------------------
    # The vision agent (scene check + second read) uses GEMINI_API_KEY. Without a key, or
    # with CS1_USE_VISION=false, frames are read offline (OCR + barcode) and the scene is not checked.
    cs1_use_vision: bool = True
    cs1_vision_model: str = "gemini-3.5-flash"
    cs1_vision_per_minute: int = 10          # stay inside the free-tier rate limit
    cs1_workers: int = 2
    cs1_max_upload_mb: int = 500             # one batch can hold hundreds of frames

    # --- Case Study 3: digest delivery -----------------------------------------
    # Email via any SMTP server (e.g. Gmail with an app password). When SMTP is not
    # configured, digests are written to storage/cs3_outbox/ so the flow still works.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    cs3_managers_file: Path = PROJECT_ROOT / "data" / "case_study_3" / "fc_managers.csv"
    cs3_default_manager_email: str = ""
    # Daily automatic digest time (24h "HH:MM", server local time). Empty = only manual sending.
    cs3_digest_time: str = ""

    @property
    def upload_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def report_dir(self) -> Path:
        return self.storage_dir / "reports"

    @property
    def cs1_frame_dir(self) -> Path:
        return self.storage_dir / "cs1_frames"

    @property
    def cs1_vision_enabled(self) -> bool:
        return self.cs1_use_vision and bool(self.gemini_api_key)

    @property
    def cs3_outbox_dir(self) -> Path:
        return self.storage_dir / "cs3_outbox"

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        defaults = cls()
        return cls(
            mongo_uri=os.getenv("MONGO_URI", defaults.mongo_uri),
            mongo_db_name=os.getenv("MONGO_DB_NAME", defaults.mongo_db_name),
            allow_in_memory_db=_env_bool("ALLOW_IN_MEMORY_DB", defaults.allow_in_memory_db),
            force_in_memory_db=_env_bool("FORCE_IN_MEMORY_DB", defaults.force_in_memory_db),
            storage_dir=Path(os.getenv("STORAGE_DIR", str(defaults.storage_dir))),
            max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", defaults.max_upload_mb)),
            job_workers=int(os.getenv("JOB_WORKERS", defaults.job_workers)),
            llm_provider=os.getenv("LLM_PROVIDER", defaults.llm_provider).lower(),
            gemini_api_key=os.getenv("GEMINI_API_KEY", defaults.gemini_api_key),
            gemini_model=os.getenv("GEMINI_MODEL", defaults.gemini_model),
            ollama_url=os.getenv("OLLAMA_URL", defaults.ollama_url),
            ollama_model=os.getenv("OLLAMA_MODEL", defaults.ollama_model),
            cs1_use_vision=_env_bool("CS1_USE_VISION", defaults.cs1_use_vision),
            cs1_vision_model=os.getenv("CS1_VISION_MODEL", defaults.cs1_vision_model),
            cs1_vision_per_minute=int(os.getenv("CS1_VISION_PER_MINUTE", defaults.cs1_vision_per_minute)),
            cs1_workers=int(os.getenv("CS1_WORKERS", defaults.cs1_workers)),
            cs1_max_upload_mb=int(os.getenv("CS1_MAX_UPLOAD_MB", defaults.cs1_max_upload_mb)),
            smtp_host=os.getenv("SMTP_HOST", defaults.smtp_host),
            smtp_port=int(os.getenv("SMTP_PORT", defaults.smtp_port)),
            smtp_user=os.getenv("SMTP_USER", defaults.smtp_user),
            smtp_password=os.getenv("SMTP_PASSWORD", defaults.smtp_password),
            smtp_from=os.getenv("SMTP_FROM", defaults.smtp_from),
            cs3_managers_file=Path(os.getenv("CS3_MANAGERS_FILE", str(defaults.cs3_managers_file))),
            cs3_default_manager_email=os.getenv("CS3_DEFAULT_MANAGER_EMAIL", defaults.cs3_default_manager_email),
            cs3_digest_time=os.getenv("CS3_DIGEST_TIME", defaults.cs3_digest_time).strip(),
        )
