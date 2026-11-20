"""LLM 출구. rag·agent의 OpenAI 호환 요청(`POST /v1/chat/completions`)을 받아 정책을 확인하고 LiteLLM 프록시로 넘깁니다.

순서
1. `X-Delegation-Token`이 있으면 이 gateway가 서명한 토큰인지 확인하고 `agt`로 에이전트를 찾습니다.
2. `model`은 LiteLLM 설정의 별칭만 받습니다. 별칭마다 `model_info.location`(local·external)이 있습니다.
3. 정책: 에이전트 model_policy가 local_only이거나 위임 토큰이 없으면 외부 별칭을 막습니다(403 model-policy).
4. 본문에서 토큰 모양 문자열을 가립니다. 토큰 헤더는 넘기지 않습니다.
5. 외부 별칭이면 사내 용어 사전(gateway/confidential.py)으로 기밀을 판정해 차단(403 confidential)하거나 로컬 별칭으로
   돌립니다. 그래도 외부로 나가면 한국어 개인정보를 가립니다(gateway/pii.py). 둘 다 감사 이벤트 llm.redacted를 남깁니다.
   로컬 모델로 가는 요청은 가리지 않습니다.
6. 외부로 나간 요청은 가림 전후 본문과 응답을 egress.jsonl에, 모든 요청은 감사 이벤트 llm.request로 남깁니다.
7. 시간 초과(504)·연결 실패(502)·LiteLLM 5xx(502)는 실패 알림을 보냅니다.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import httpx
import jwt
import yaml
from fastapi import Request
from fastapi.responses import Response, StreamingResponse

from gateway.alerts import Alerter
from gateway.audit import AuditLog, now_iso
from gateway.confidential import Glossary
from gateway.problems import ProblemError
from gateway.redact import scrub
from gateway.registry import AgentEntry, Registry
from gateway.tokens import DelegationTokenIssuer

log = logging.getLogger(__name__)

TOKEN_HEADER = "x-delegation-token"

# 가림 단계: 본문을 받아 (보낼 본문, 개체 종류별 가린 개수)를 돌려줍니다(gateway/pii.py).
Redactor = Callable[[dict[str, Any]], tuple[dict[str, Any], Counter]]


def no_redaction(body: dict[str, Any]) -> tuple[dict[str, Any], Counter]:
    return body, Counter()


def load_model_locations(config_path: Path) -> dict[str, str]:
    doc = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for m in doc.get("model_list", []):
        loc = (m.get("model_info") or {}).get("location")
        if loc not in ("local", "external"):
            raise ValueError(f"LiteLLM 별칭 {m.get('model_name')}에 model_info.location(local|external)이 없습니다")
        out[m["model_name"]] = loc
    return out


@dataclass(frozen=True)
class Caller:
    employee_id: str | None
    agent: AgentEntry | None
    conversation_id: str | None

    @property
    def via_token(self) -> bool:
        return self.agent is not None


def policy_denial(caller: Caller, location: str) -> str | None:
    """막아야 하면 사용자에게 보여 줄 이유를, 아니면 None을 돌려줍니다."""
    if location != "external":
        return None
    if caller.agent is None:
        return "위임 토큰이 없는 호출은 로컬 모델만 쓸 수 있습니다"
    if caller.agent.model_policy.get("mode") != "external_allowed":
        return f"에이전트 {caller.agent.id}는 외부 모델을 쓸 수 없습니다(local_only)"
    return None


class Egress:
    def __init__(self, *, base_url: str, locations: dict[str, str], registry: Registry,
                 issuer: DelegationTokenIssuer, audit: AuditLog, alerter: Alerter, timeout: float,
                 api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 redactor: Redactor = no_redaction, glossary: Glossary | None = None):
        self.locations = locations
        self.registry, self.issuer, self.audit, self.alerter = registry, issuer, audit, alerter
        self.redactor = redactor
        self.glossary = glossary or Glossary([])
        self.local_alias = next((a for a, loc in locations.items() if loc == "local"), None)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, headers=headers,
                                       timeout=httpx.Timeout(timeout, connect=5.0))
        self._timeout = timeout

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---------- 요청 해석 ----------
    def _caller(self, request: Request) -> Caller:
        token = request.headers.get(TOKEN_HEADER)
        if not token:
            return Caller(None, None, None)
        try:
            claims = self.issuer.verify(token)
        except jwt.PyJWTError as e:
            raise ProblemError(401, "unauthorized", "위임 토큰을 확인하지 못했습니다", type(e).__name__)
        agent = self.registry.get(claims["agt"])
        if agent is None:
            raise ProblemError(403, "forbidden", "등록부에 없는 에이전트입니다", claims["agt"])
        return Caller(claims["sub"], agent, claims["cid"])

    @staticmethod
    async def _body(request: Request) -> dict[str, Any]:
        try:
            body = json.loads(await request.body())
        except ValueError:
            raise ProblemError(422, "validation", "JSON 본문이 아닙니다")
        if not isinstance(body, dict) or not isinstance(body.get("model"), str) or "messages" not in body:
            raise ProblemError(422, "validation", "model과 messages가 필요합니다")
        return body

    # ---------- 처리 ----------
    async def handle(self, request: Request) -> Response:
        caller = self._caller(request)
        body = await self._body(request)
        alias = body["model"]
        location = self.locations.get(alias)
        if location is None:
            raise ProblemError(422, "validation", "모르는 모델 별칭입니다",
                               f"쓸 수 있는 별칭: {', '.join(sorted(self.locations))}")
        model = {"name": alias, "location": location, "externalSent": False, "redactions": 0}

        denial = policy_denial(caller, location)
        if denial:
            self._audit(caller, model, "denied", "urn:problem:model-policy", denial)
            raise ProblemError(403, "model-policy", "모델 정책에 맞지 않습니다", denial)

        # 토큰 모양 문자열은 어떤 모델에도 보내지 않습니다. JWT 문자에는 따옴표가 없어 JSON 문자열째 가려도 됩니다.
        before = json.loads(scrub(json.dumps(body, ensure_ascii=False)))
        sent = before
        if location == "external":
            sent = self._confidential(caller, model, before)
        if model["location"] == "external":
            sent, counts = self.redactor(sent)
            model["redactions"] = sum(counts.values())
            if counts:
                detail = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                self._audit(caller, model, "ok", detail=detail, kind="llm.redacted")

        if sent.get("stream"):
            return await self._stream(caller, model, before, sent)
        return await self._once(caller, model, before, sent)

    def _confidential(self, caller: Caller, model: dict, body: dict) -> dict:
        """사내 기밀 용어가 있으면 차단하거나 로컬 별칭으로 바꾼 본문을 돌려줍니다."""
        verdict = self.glossary.check(body)
        if verdict is None:
            return body
        if verdict.action == "block" or self.local_alias is None:
            detail = f"기밀 용어 {verdict.hits}개: 차단"
            self._audit(caller, model, "denied", "urn:problem:confidential", detail)
            raise ProblemError(403, "confidential", "사내 기밀이 들어 있어 보낼 수 없습니다", verdict.reason)
        self._audit(caller, model, "ok", detail=f"기밀 용어 {verdict.hits}개: 로컬 모델로 돌림", kind="llm.redacted")
        model.update(name=self.local_alias, location="local")
        return {**body, "model": self.local_alias}

    async def _once(self, caller: Caller, model: dict, before: dict, sent: dict) -> Response:
        try:
            r = await self._http.post("/v1/chat/completions", json=sent)
        except httpx.HTTPError as e:
            await self._fail(caller, model, e)
        model["externalSent"] = model["location"] == "external"
        if r.status_code >= 500:
            await self._upstream_error(caller, model, before, sent, r.status_code, r.text)
        self._egress(caller, model, before, sent, r.status_code, r.text)
        self._audit(caller, model, "ok" if r.status_code < 400 else "error",
                    None if r.status_code < 400 else f"urn:problem:llm-status-{r.status_code}")
        return Response(r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))

    async def _stream(self, caller: Caller, model: dict, before: dict, sent: dict) -> Response:
        req = self._http.build_request("POST", "/v1/chat/completions", json=sent)
        try:
            r = await self._http.send(req, stream=True)
        except httpx.HTTPError as e:
            await self._fail(caller, model, e)
        model["externalSent"] = model["location"] == "external"
        if r.status_code >= 400:
            text = (await r.aread()).decode("utf-8", "replace")
            await r.aclose()
            if r.status_code >= 500:
                await self._upstream_error(caller, model, before, sent, r.status_code, text)
            self._egress(caller, model, before, sent, r.status_code, text)
            self._audit(caller, model, "error", f"urn:problem:llm-status-{r.status_code}")
            return Response(text, status_code=r.status_code,
                            media_type=r.headers.get("content-type", "application/json"))

        async def relay() -> AsyncIterator[bytes]:
            chunks: list[bytes] = []
            try:
                async for chunk in r.aiter_bytes():  # 압축은 풀어서 넘깁니다(content-encoding 헤더를 넘기지 않음)
                    chunks.append(chunk)
                    yield chunk
            except httpx.HTTPError as e:
                await self.alerter.alert(f"LLM 스트림 중단 model={model['name']} ({type(e).__name__})")
                self._egress(caller, model, before, sent, r.status_code, b"".join(chunks).decode("utf-8", "replace"))
                self._audit(caller, model, "error", "urn:problem:llm-stream-broken", type(e).__name__)
                return
            finally:
                await r.aclose()
            self._egress(caller, model, before, sent, r.status_code, b"".join(chunks).decode("utf-8", "replace"))
            self._audit(caller, model, "ok")

        return StreamingResponse(relay(), status_code=r.status_code,
                                 media_type=r.headers.get("content-type", "text/event-stream"))

    # ---------- 실패·기록 ----------
    async def _fail(self, caller: Caller, model: dict, e: httpx.HTTPError) -> NoReturn:
        if isinstance(e, httpx.TimeoutException):
            status, code, title = 504, "llm-timeout", f"모델이 {self._timeout:g}초 안에 답하지 않았습니다"
        else:
            status, code, title = 502, "llm-unavailable", "LLM 프록시에 연결하지 못했습니다"
        # 연결 전 실패가 아니면(읽기 시간 초과 등) 요청은 이미 나갔다고 봅니다.
        model["externalSent"] = model["location"] == "external" and not isinstance(e, httpx.ConnectError)
        await self.alerter.alert(f"{title} model={model['name']} ({type(e).__name__})")
        self._audit(caller, model, "error", f"urn:problem:{code}", type(e).__name__)
        raise ProblemError(status, code, title)

    async def _upstream_error(self, caller: Caller, model: dict, before: dict, sent: dict,
                              status: int, text: str) -> NoReturn:
        await self.alerter.alert(f"LLM 프록시 오류 {status} model={model['name']}")
        self._egress(caller, model, before, sent, status, text)
        self._audit(caller, model, "error", "urn:problem:llm-upstream-error", f"status {status}")
        raise ProblemError(502, "llm-upstream-error", "모델 호출이 실패했습니다", f"LiteLLM {status}")

    def _audit(self, caller: Caller, model: dict, result: str, problem_type: str | None = None,
               detail: str | None = None, kind: str = "llm.request") -> None:
        self.audit.event(kind, employee_id=caller.employee_id,
                         agent_id=caller.agent.id if caller.agent else None, via_token=caller.via_token,
                         conversation_id=caller.conversation_id, model=dict(model), result=result,
                         problem_type=problem_type, detail=detail)

    def _egress(self, caller: Caller, model: dict, before: dict, sent: dict, status: int, response: str) -> None:
        if model["location"] != "external":
            return
        self.audit.egress.write({
            "occurredAt": now_iso(),
            "employeeId": caller.employee_id,
            "agentId": caller.agent.id if caller.agent else None,
            "conversationId": caller.conversation_id,
            "model": model["name"],
            "redactions": model["redactions"],
            "requestBeforeRedaction": before,
            "requestSent": sent,
            "status": status,
            "response": scrub(response),
        })

