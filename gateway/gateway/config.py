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
    audit_event_files: tuple[str, ...] = ()
    agent_base_url: str = "http://localhost:8020"
    agent_timeout_seconds: float = 120.0
    external_log: Path | None = None   # GATEWAY_EXTERNAL_LOG: 평가용 외부 요청 기록(JSON Lines)
    eval_mode: bool = False            # GATEWAY_EVAL_MODE=1: X-Eval-Condition을 받음
    eval_toolcall: bool = False        # GATEWAY_EVAL_TOOLCALL=1: 토큰 없는 외부 호출을 받음(#294, 도구 호출 측정 스택만)
    pack_stage: int | None = None      # GATEWAY_PACK_STAGE: pack.yaml stage 덮어쓰기(#170). 없으면 pack.yaml
    slack_bridge_secret: str | None = None      # SLACK_BRIDGE_SECRET: 없으면 /auth/slack 꺼짐(404, #273)
    slack_users_file: Path = REPO_ROOT / "infra/slack/slack-users.json"  # SLACK_USERS_FILE: 슬랙 사용자 ID → 직원 ID
    erp_service_login_secret: str | None = None  # ERP_SERVICE_LOGIN_SECRET: erp /auth/service-login 비밀값
    slack_login_per_user_per_minute: int = 10    # SLACK_LOGIN_PER_USER_PER_MINUTE: 슬랙 사용자 ID별 분당 상한(#331)
    slack_login_per_minute: int = 60             # SLACK_LOGIN_PER_MINUTE: /auth/slack 전체 분당 상한(틀린 비밀값 포함)

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
            agent_base_url=os.environ.get("AGENT_BASE_URL", "http://localhost:8020").rstrip("/"),
            agent_timeout_seconds=float(os.environ.get("AGENT_TIMEOUT_SECONDS", "120")),
            external_log=_path(os.environ["GATEWAY_EXTERNAL_LOG"], REPO_ROOT)
            if os.environ.get("GATEWAY_EXTERNAL_LOG") else None,
            eval_mode=os.environ.get("GATEWAY_EVAL_MODE") == "1",
            eval_toolcall=os.environ.get("GATEWAY_EVAL_TOOLCALL") == "1",
            pack_stage=int(os.environ["GATEWAY_PACK_STAGE"]) if os.environ.get("GATEWAY_PACK_STAGE") else None,
            slack_bridge_secret=os.environ.get("SLACK_BRIDGE_SECRET") or None,
            slack_users_file=_path(os.environ.get("SLACK_USERS_FILE"), REPO_ROOT / "infra/slack/slack-users.json"),
            erp_service_login_secret=os.environ.get("ERP_SERVICE_LOGIN_SECRET") or None,
            slack_login_per_user_per_minute=int(os.environ.get("SLACK_LOGIN_PER_USER_PER_MINUTE") or 10),
            slack_login_per_minute=int(os.environ.get("SLACK_LOGIN_PER_MINUTE") or 60),
            audit_event_files=tuple(x.strip() for x in os.environ.get("AUDIT_EVENT_FILES", "").split(",") if x.strip()),
        )
