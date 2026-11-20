"""위임 토큰 확인. gateway가 서명한 ES256 JWT이고, aud에 rag가 있고, 만료되지 않아야 합니다.

공개 키는 `DELEGATION_TOKEN_PUBLIC_KEY`(PEM 파일 경로) 또는 `DELEGATION_JWKS_URL`(gateway JWKS)로 받습니다.
토큰 문자열은 로그와 감사 기록에 남기지 않습니다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import jwt

from rag.pack import REPO_ROOT

REQUIRED = ["iss", "aud", "sub", "agt", "cid", "doc_scopes", "iat", "exp", "jti"]


class AuthError(Exception):
    pass


class TokenVerifier:
    def __init__(self, key: Any = None, jwks_url: str | None = None, leeway: int = 5):
        if key is None and jwks_url is None:
            raise ValueError("공개 키나 JWKS 주소가 있어야 합니다")
        self._key = key
        self._jwks = jwt.PyJWKClient(jwks_url) if jwks_url else None
        self._leeway = leeway

    @classmethod
    def from_env(cls) -> TokenVerifier:
        if path := os.environ.get("DELEGATION_TOKEN_PUBLIC_KEY"):
            p = Path(path)
            return cls(key=(p if p.is_absolute() else REPO_ROOT / p).read_text(encoding="utf-8"))
        if url := os.environ.get("DELEGATION_JWKS_URL"):
            return cls(jwks_url=url)
        raise ValueError("DELEGATION_TOKEN_PUBLIC_KEY나 DELEGATION_JWKS_URL이 필요합니다")

    def verify(self, token: str | None) -> dict[str, Any]:
        if not token:
            raise AuthError("위임 토큰이 없습니다")
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key if self._jwks else self._key
            claims = jwt.decode(
                token, key, algorithms=["ES256"], audience="rag", issuer="gateway",
                leeway=self._leeway, options={"require": REQUIRED},
            )
        except jwt.PyJWTError as e:
            raise AuthError(f"위임 토큰이 올바르지 않습니다({type(e).__name__})") from e
        if not isinstance(claims["doc_scopes"], list):
            raise AuthError("doc_scopes 형식이 다릅니다")
        return claims
