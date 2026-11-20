"""환경 변수에서 읽는 설정. 비밀값은 값이 아니라 경로나 환경 변수 이름으로만 다룹니다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


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

    @classmethod
    def from_env(cls) -> Settings:
        key = os.environ.get("DELEGATION_TOKEN_PRIVATE_KEY")
        return cls(
            erp_base_url=os.environ.get("ERP_BASE_URL", "http://localhost:8040/api/v1").rstrip("/"),
            pack_dir=_path(os.environ.get("PACK_DIR"), REPO_ROOT / "packs/manufacturing"),
            contracts_dir=_path(os.environ.get("CONTRACTS_DIR"), REPO_ROOT / "contracts"),
            delegation_private_key=_path(key, REPO_ROOT) if key else None,
        )
