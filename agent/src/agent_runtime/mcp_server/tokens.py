"""위임 토큰(contracts/auth/delegation-token.schema.json) 확인.

gateway 공개 키로 ES256 서명, iss=gateway, aud에 mcp, 만료를 확인합니다. 토큰 문자열은 로그·오류 메시지에 넣지 않습니다.
키는 DELEGATION_TOKEN_PUBLIC_KEY(PEM 파일 경로)나 DELEGATION_JWKS_URL(gateway JWKS)에서 읽습니다.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt

REQUIRED_CLAIMS = ["iss", "aud", "sub", "agt", "cid", "scopes", "doc_scopes", "iat", "exp", "jti"]


class TokenError(Exception):
    """토큰이 없거나 틀림. 메시지에는 토큰 내용을 넣지 않습니다."""


@dataclass(frozen=True)
class Delegation:
    employee_id: str
    agent_id: str
    conversation_id: str
    scopes: frozenset[str]
    tools: frozenset[str]
    jti: str


KeyResolver = Callable[[str], Any]


class TokenVerifier:
    def __init__(self, key_for: KeyResolver, leeway_s: int = 5) -> None:
        self._key_for = key_for
        self._leeway = leeway_s

    @classmethod
    def from_public_key(cls, pem: str) -> TokenVerifier:
        return cls(lambda _token: pem)

    @classmethod
    def from_env(cls) -> TokenVerifier:
        path = os.environ.get("DELEGATION_TOKEN_PUBLIC_KEY")
        if path and Path(path).is_file():
            return cls.from_public_key(Path(path).read_text("utf-8"))
        url = os.environ.get("DELEGATION_JWKS_URL")
        if url:
            client = jwt.PyJWKClient(url, cache_keys=True)
            return cls(lambda token: client.get_signing_key_from_jwt(token).key)
        raise RuntimeError("DELEGATION_TOKEN_PUBLIC_KEY(파일)나 DELEGATION_JWKS_URL이 필요합니다")

    def verify(self, token: str | None) -> Delegation:
        if not token:
            raise TokenError("위임 토큰이 없습니다")
        try:
            claims = jwt.decode(
                token,
                self._key_for(token),
                algorithms=["ES256"],
                audience="mcp",
                issuer="gateway",
                leeway=self._leeway,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError as e:
            raise TokenError(f"위임 토큰을 확인하지 못했습니다({type(e).__name__})") from None
        return Delegation(
            employee_id=str(claims["sub"]),
            agent_id=str(claims["agt"]),
            conversation_id=str(claims["cid"]),
            scopes=frozenset(claims.get("scopes") or []),
            tools=frozenset(claims.get("tools") or []),
            jti=str(claims["jti"]),
        )
