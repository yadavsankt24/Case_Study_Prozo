"""
MongoDB connection (shared by all case studies).

Each case study's repository creates its own collections and indexes.
Uses a real MongoDB server when reachable. For a quick demo on a laptop
without MongoDB, it falls back to `mongomock` (an in-memory MongoDB with the
same API) and logs a clear warning - data then lives only while the app runs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.config import Settings

log = logging.getLogger(__name__)


@dataclass
class DatabaseHandle:
    db: Database
    in_memory: bool


def connect(settings: Settings) -> DatabaseHandle:
    if not settings.force_in_memory_db:
        try:
            client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=2000, tz_aware=True)
            client.admin.command("ping")
            log.info("Connected to MongoDB at %s (db=%s)", mask_credentials(settings.mongo_uri), settings.mongo_db_name)
            return DatabaseHandle(db=client[settings.mongo_db_name], in_memory=False)
        except PyMongoError as exc:
            if not settings.allow_in_memory_db:
                raise RuntimeError(f"MongoDB is not reachable at {mask_credentials(settings.mongo_uri)}: {exc}") from exc
            log.warning("MongoDB not reachable (%s). Falling back to in-memory database.", exc)

    import mongomock  # imported lazily: only needed for demos and tests

    db = mongomock.MongoClient(tz_aware=True)[settings.mongo_db_name]
    log.warning("Using IN-MEMORY database: jobs and results are lost when the app stops.")
    return DatabaseHandle(db=db, in_memory=True)


def mask_credentials(uri: str) -> str:
    """Hide the password in a MongoDB URI before it is logged: user:secret@host -> user:****@host."""
    return re.sub(r"(//[^:/@]+):[^@]+@", r"\1:****@", uri)

