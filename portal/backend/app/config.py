import os
import secrets
from dataclasses import dataclass, field


def _env_list(name, default):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


@dataclass
class Settings:
    region: str = field(default_factory=lambda: os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1")
    table_name: str = field(default_factory=lambda: os.environ.get("PORTAL_TABLE", "ml-portal"))
    # A random secret means sessions reset on restart; set one to keep logins across restarts.
    session_secret: str = field(default_factory=lambda: os.environ.get("PORTAL_SESSION_SECRET") or secrets.token_hex(32))
    mock_auth: bool = field(default_factory=lambda: os.environ.get("PORTAL_MOCK_AUTH", "1") == "1")
    allowed_origins: list = field(default_factory=lambda: _env_list(
        "PORTAL_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
    ))
    project_role_path: str = "/mlportal/"
    project_role_policy_arns: list = field(default_factory=lambda: _env_list(
        "PORTAL_PROJECT_ROLE_POLICIES", "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
    ))
    presign_expires_seconds: int = 15
    studio_session_seconds: int = 43200
    # IAM is eventually consistent: a brand-new role can be rejected by SageMaker for a few seconds.
    profile_create_retries: int = 4
    profile_create_retry_delay: float = 5.0
    domain_cache_seconds: int = 60
