"""위임 토큰(ES256, 10분) 발급과 공개 키(JWKS).

클레임 형식은 contracts/auth/delegation-token.schema.json입니다. 범위는 "요청자 권한 ∩ 에이전트 정책"입니다.
- scopes: 에이전트 도구들의 required_scope(사람 화면 전용 scope 제외). 직원 JWT는 erp에서 모든 scope를 가지므로,
  요청자 쪽 제한은 erp가 "토큰 주인의 권한 ∩ 토큰 scopes"로 다시 판단합니다.
- doc_scopes: 요청자 문서 접근 태그 ∩ 에이전트 doc_scopes
토큰 문자열은 돌려주기만 하고 로그에 쓰지 않습니다. 로그에는 jti만 남깁니다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from gateway.registry import AgentEntry, Requester

log = logging.getLogger(__name__)

AUDIENCE = ["erp", "rag", "mcp"]


def _b64(n: int) -> str:
    return base64.urlsafe_b64encode(n.to_bytes(32, "big")).rstrip(b"=").decode()


@dataclass(frozen=True)
class IssuedToken:
    token: str
    claims: dict[str, Any]


class DelegationTokenIssuer:
    def __init__(self, private_key: ec.EllipticCurvePrivateKey, ttl_seconds: int = 600):
        if not isinstance(private_key.curve, ec.SECP256R1):
            raise ValueError("위임 토큰 키는 P-256(ES256)이어야 합니다")
        self._key = private_key
        self.ttl = ttl_seconds
        nums = private_key.public_key().public_numbers()
        self._jwk = {"kty": "EC", "crv": "P-256", "x": _b64(nums.x), "y": _b64(nums.y)}
        # RFC 7638 지문을 kid로 씁니다.
        canon = json.dumps(self._jwk, separators=(",", ":"), sort_keys=True).encode()
        self.kid = base64.urlsafe_b64encode(hashlib.sha256(canon).digest()).rstrip(b"=").decode()

    @classmethod
    def from_pem_file(cls, path: Path, ttl_seconds: int = 600) -> DelegationTokenIssuer:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise ValueError("위임 토큰 키는 EC 개인 키여야 합니다")
        return cls(key, ttl_seconds)

    @classmethod
    def ephemeral(cls, ttl_seconds: int = 600) -> DelegationTokenIssuer:
        return cls(ec.generate_private_key(ec.SECP256R1()), ttl_seconds)

    def public_pem(self) -> str:
        return self._key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()

    def jwks(self) -> dict[str, Any]:
        return {"keys": [{**self._jwk, "kid": self.kid, "use": "sig", "alg": "ES256"}]}

    def verify(self, token: str) -> dict[str, Any]:
        """이 gateway가 서명한 위임 토큰인지, 만료되지 않았는지 봅니다. 틀리면 jwt.PyJWTError를 냅니다."""
        return jwt.decode(token, self._key.public_key(), algorithms=["ES256"], issuer="gateway",
                          options={"verify_aud": False, "require": ["exp", "iat", "sub", "agt", "cid"]})

    def issue(self, requester: Requester, agent: AgentEntry, conversation_id: str,
              now: int | None = None) -> IssuedToken:
        iat = int(time.time()) if now is None else now
        claims: dict[str, Any] = {
            "iss": "gateway",
            "aud": AUDIENCE,
            "sub": requester.id,
            "agt": agent.id,
            "cid": conversation_id,
            "scopes": list(agent.scopes),
            "tools": list(agent.tools),
            "doc_scopes": sorted(set(requester.access_tags) & set(agent.doc_scopes)),
            "iat": iat,
            "exp": iat + self.ttl,
            "jti": uuid.uuid4().hex,
        }
        token = jwt.encode(claims, self._key, algorithm="ES256", headers={"kid": self.kid})
        log.info("위임 토큰 발급 jti=%s sub=%s agt=%s cid=%s", claims["jti"], requester.id, agent.id,
                 conversation_id)
        return IssuedToken(token=token, claims=claims)
