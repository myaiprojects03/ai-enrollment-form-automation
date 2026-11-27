"""Everything the engine runs on, built once: used by the API server and by the background worker alike."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import asyncpg

from app.config import Settings
from app.db.migrations import connect
from app.enrollments.intake import Intake
from app.enrollments.pipeline import Pipeline
from app.enrollments.store import EnrollmentStore
from app.mapping.llm import LLMClient, build_llm
from app.mapping.mapper import Mapper
from app.security import masking
from app.security.crypto import FieldCipher, Fingerprinter
from app.shared.store import SharedStore, build_store
from app.submit.browser import BrowserSubmitter
from app.submit.portal_api import PortalAPI
from app.submit.runner import Submitter
from app.submit.store import RunStore


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    masking.install()
    logging.getLogger("httpx").setLevel(logging.WARNING)   # request lines can carry an email in the query


@dataclass
class Services:
    pool: asyncpg.Pool
    shared: SharedStore
    enrollments: EnrollmentStore
    intake: Intake
    pipeline: Pipeline
    runs: RunStore
    submitter: Submitter
    llm: LLMClient | None

    async def aclose(self) -> None:
        await self.shared.aclose()
        await self.pool.close()


async def build(settings: Settings) -> Services:
    if settings.is_production and settings.production_problems():
        raise RuntimeError("unsafe production settings: " + "; ".join(settings.production_problems()))
    if not settings.encryption_keys or not settings.fingerprint_key:
        raise RuntimeError("ENCRYPTION_KEYS and FINGERPRINT_KEY are required (python -m scripts.keys)")
    cipher = FieldCipher.from_setting(settings.encryption_keys)
    fingerprints = Fingerprinter(settings.fingerprint_key)
    pool = await connect(settings.database_url)
    shared = await build_store(settings.redis_url, settings.is_production)
    enrollments = EnrollmentStore(pool, cipher)
    llm = build_llm(settings.llm_provider, groq_api_key=settings.groq_api_key, groq_model=settings.groq_model,
                    anthropic_api_key=settings.anthropic_api_key, anthropic_model=settings.anthropic_model)
    runs = RunStore(pool, cipher)
    submitter = Submitter(enrollments, runs, shared, PortalAPI(settings.portal_base_url, settings.portal_api_key),
                          BrowserSubmitter(settings.portal_base_url, headless=settings.browser_headless),
                          max_attempts=settings.submit_max_attempts, backoff_s=settings.submit_backoff_s,
                          alert_url=settings.alert_webhook_url)
    return Services(
        pool=pool, shared=shared, enrollments=enrollments,
        intake=Intake(enrollments, shared, fingerprints, settings.idempotency_ttl_s),
        pipeline=Pipeline(enrollments, Mapper(llm, settings.llm_free_text), fingerprints, settings.review_threshold),
        runs=runs, submitter=submitter, llm=llm)
