"""Central settings. Secrets come only from environment variables (or the project-root .env), never code."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    app_env: str = "development"                   # development | production
    allowed_origins: str = "http://localhost:3000"  # the review console (comma-separated)

    # ---- Storage ----
    database_url: str = "postgresql://enroll:enroll@localhost:5433/enroll"
    redis_url: str = "redis://localhost:6380/0"     # "" = in-memory (one process, development only)

    # ---- Personal data protection ----
    # 32 random bytes, base64. Encrypts applicant data at rest (AES-256-GCM). Several keys, comma-separated, rotate:
    # the first encrypts, all of them decrypt. Create one with: python -m scripts.keys
    encryption_keys: str = ""
    # Separate secret for lookup fingerprints (duplicate detection without storing an email in clear).
    fingerprint_key: str = ""

    # ---- Access ----
    # Operator API token (Bearer) for the engine's private endpoints until staff sign-in arrives (phase 4).
    operator_token: str = ""
    # Review console sign-in. Comma-separated "email:scrypt$..." entries (python -m scripts.staff you@example.com),
    # and the secret that signs sessions. Reviewers' names then appear in the audit trail.
    staff_accounts: str = ""
    session_secret: str = ""
    session_hours: int = 8

    # ---- AI field mapping ----
    # groq (free tier), anthropic (Claude), auto (whichever key is set), or none (rules only).
    llm_provider: str = "groq"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"
    # Free text (notes, letters, PDFs without form fields) can only be read by sending it to the model.
    # Structured records never send values, only column names and value shapes. false = free text goes to a person.
    llm_free_text: bool = True
    # Fields mapped below this confidence go to a person.
    review_threshold: float = 0.85

    # ---- Webhooks ----
    # HMAC-SHA256 secret for POST /api/webhooks/intake (header X-Signature: sha256=<hex>). Empty = webhook off.
    webhook_secret: str = ""

    # ---- Submission ----
    portal_base_url: str = "http://localhost:3000"   # where the two portals run
    portal_api_key: str = "dev-portal-key"           # X-Portal-Key for their APIs (the portals' PORTAL_API_KEY)
    browser_headless: bool = True
    submit_max_attempts: int = 3
    submit_backoff_s: float = 2.0                    # 2 s, 4 s, ... with jitter
    # How a submission that needs the browser is run: "inline" in this process (local, a container), or "dispatch":
    # hand it to the worker by triggering the GitHub Actions workflow (serverless hosting, where the API has no
    # browser and cannot keep work running after it answers). API-path submissions always run inline.
    submit_mode: str = "inline"
    github_dispatch_repo: str = ""                  # owner/repo
    github_dispatch_token: str = ""                 # fine-grained token with Actions: read and write on that repo
    # Chat webhook (Slack, Teams, Discord, Google Chat) told when a submission fails or needs a person.
    alert_webhook_url: str = ""
    # Personal data of submitted and rejected enrollments is erased after this many days (scripts/purge.py).
    retention_days: int = 90
    # Test modes on a submit (?variant=b, ?chaos=flaky) for demos and tests. Off in production.
    allow_test_modes: bool = True

    # ---- Idempotency ----
    idempotency_ttl_s: int = 7 * 24 * 3600          # how long a replayed key is recognised in Redis

    def production_problems(self) -> list[str]:
        """Settings that are unsafe for a live deployment. The app refuses to start in production if any are found."""
        problems = []
        if len(self.operator_token) < 24:
            problems.append("OPERATOR_TOKEN must be at least 24 characters")
        if len(self.session_secret) < 24:
            problems.append("SESSION_SECRET must be at least 24 characters")
        if self.portal_api_key in ("", "dev-portal-key"):
            problems.append("PORTAL_API_KEY must be set to a private value")
        if not self.redis_url:
            problems.append("REDIS_URL is required")
        if self.submit_mode == "dispatch" and not (self.github_dispatch_repo and self.github_dispatch_token):
            problems.append("SUBMIT_MODE=dispatch needs GITHUB_DISPATCH_REPO and GITHUB_DISPATCH_TOKEN")
        return problems

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
