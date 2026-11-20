"""환경 변수에서 읽는 설정. 비밀값은 값이 아니라 경로나 환경 변수 이름으로만 다룹니다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parent


def _path(value: str | None, default: Path) -> Path:
    if not value:
        return default
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


@dataclass(frozen=True)
class Settings:
    erp_base_url: str
    pack_dir: Path
    contracts_dir: Path
    delegation_private_key: Path | None
    token_ttl_seconds: int = 600
    litellm_base_url: str = "http://localhost:4000"
    litellm_config: Path = MODULE_ROOT / "litellm/config.yaml"
    llm_timeout_seconds: float = 60.0
    audit_dir: Path = MODULE_ROOT / "var"
    alert_webhook_url: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        key = os.environ.get("DELEGATION_TOKEN_PRIVATE_KEY")
        return cls(
            erp_base_url=os.environ.get("ERP_BASE_URL", "http://localhost:8040/api/v1").rstrip("/"),
            pack_dir=_path(os.environ.get("PACK_DIR"), REPO_ROOT / "packs/manufacturing"),
            contracts_dir=_path(os.environ.get("CONTRACTS_DIR"), REPO_ROOT / "contracts"),
            delegation_private_key=_path(key, REPO_ROOT) if key else None,
            litellm_base_url=os.environ.get("LITELLM_BASE_URL", "http://localhost:4000").rstrip("/"),
            litellm_config=_path(os.environ.get("LITELLM_CONFIG"), MODULE_ROOT / "litellm/config.yaml"),
            llm_timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "60")),
            audit_dir=_path(os.environ.get("GATEWAY_AUDIT_DIR"), MODULE_ROOT / "var"),
            alert_webhook_url=os.environ.get("ALERT_WEBHOOK_URL") or None,
        )
