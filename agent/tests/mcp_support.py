"""MCP 시험 준비: 시험용 ES256 키, 위임 토큰 발급, 프로세스 안의 가짜 erp, 녹화 대신 쓰는 rag 스텁."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from agent_runtime.audit import AuditLog
from agent_runtime.mcp_server.catalog import Catalog
from agent_runtime.mcp_server.service import ToolService
from agent_runtime.mcp_server.tokens import TokenVerifier
from agent_runtime.registry import Registry
from fakes.erp.app import create_app as create_fake_erp
from tests.conftest import CONTRACTS, PACK_DIR

KST = ZoneInfo("Asia/Seoul")
STAGE_MAX = 9  # 시험용 토큰 발급 때 모든 단계의 에이전트 도구를 찾으려고 씁니다
ALL_SCOPES = [s["id"] for s in json.loads((CONTRACTS / "auth" / "scopes.json").read_text("utf-8"))["scopes"]
              if not s.get("human_only")] + ["approval:request:leave"]


def _keypair() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv, pub


PRIVATE_KEY, PUBLIC_KEY = _keypair()
OTHER_PRIVATE_KEY, _ = _keypair()


def mint(employee: str = "E0016", agent: str = "hr", tools: list[str] | None = None,
         scopes: list[str] | None = None, aud: list[str] | None = None, ttl: int = 600,
         key: str = PRIVATE_KEY, cid: str | None = None) -> str:
    registry = Registry.load(PACK_DIR, stage=STAGE_MAX)
    t = int(time.time())
    return jwt.encode({
        "iss": "gateway", "aud": aud or ["erp", "rag", "mcp"], "sub": employee, "agt": agent,
        "cid": cid or f"cnv_{uuid.uuid4().hex[:8]}",
        "scopes": ALL_SCOPES if scopes is None else scopes,
        "tools": list(registry.get(agent).tools) if tools is None else tools,
        "doc_scopes": ["public"], "iat": t, "exp": t + ttl, "jti": uuid.uuid4().hex,
    }, key, algorithm="ES256")


@dataclass
class RagStub:
    calls: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return httpx.Response(200, json={"found": True, "answer": "출장비는 실비로 정산합니다.", "citations": []})


@dataclass
class Harness:
    service: ToolService
    audit_path: Path
    rag: RagStub

    def events(self) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        return [json.loads(x) for x in self.audit_path.read_text("utf-8").splitlines()]


def make_harness(tmp_path: Path, stage: int | None = None) -> Harness:
    registry = Registry.load(PACK_DIR, stage=stage)
    catalog = Catalog.load(CONTRACTS / "mcp" / "tools.json", CONTRACTS / "openapi", registry)
    erp_app = create_fake_erp(PACK_DIR, delegation_public_key=PUBLIC_KEY)
    rag = RagStub()
    backends = {
        "erp": httpx.AsyncClient(transport=httpx.ASGITransport(app=erp_app), base_url="http://erp.test"),
        "rag": httpx.AsyncClient(transport=httpx.MockTransport(rag), base_url="http://rag.test"),
    }
    audit_path = tmp_path / "mcp-audit.jsonl"
    service = ToolService(catalog, registry, TokenVerifier.from_public_key(PUBLIC_KEY), backends,
                          AuditLog(audit_path))
    return Harness(service, audit_path, rag)


_day = [0]


def future_weekday() -> str:
    _day[0] += 1
    d = datetime.now(KST).date() + timedelta(days=30 + _day[0])
    while d.weekday() >= 5:
        d += timedelta(days=1)
        _day[0] += 1
    return d.isoformat()


_slot = [0]


def future_slot() -> tuple[str, str]:
    _slot[0] += 1
    day = datetime.now(KST).date() + timedelta(days=50 + _slot[0] // 4)
    start = datetime(day.year, day.month, day.day, 9 + (_slot[0] % 4) * 2, 0, tzinfo=KST)
    return start.isoformat(), (start + timedelta(hours=1)).isoformat()
