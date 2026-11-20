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
from contextvars import ContextVar
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
from gateway.audit import AuditLog, JsonlWriter, now_iso
from gateway.confidential import Glossary
from gateway.problems import ProblemError
from gateway.redact import scrub
from gateway.registry import AgentEntry, Registry
from gateway.tokens import DelegationTokenIssuer

log = logging.getLogger(__name__)

TOKEN_HEADER = "x-delegation-token"

# 이 요청에서 감사 이벤트를 이미 남겼는지. 거절 사유를 따로 남긴 경로(정책·기밀·장애)는 한 번만 기록합니다.
_audited: ContextVar[bool] = ContextVar("egress_audited", default=False)

# 가림 단계: 본문을 받아 (보낼 본문, 개체 종류별 가린 개수)를 돌려줍니다(gateway/pii.py).
Redactor = Callable[[dict[str, Any]], tuple[dict[str, Any], Counter]]


def no_redaction(body: dict[str, Any]) -> tuple[dict[str, Any], Counter]:
    return body, Counter()


# LiteLLM에 넘기는 본문 필드. 그 밖의 필드(fallbacks, api_base, metadata, mock_response 등)는 정책 검사를 건너뛰어
# 다른 모델로 보내게 만들 수 있어 422로 거절합니다.
ALLOWED_FIELDS = frozenset({
    "model", "messages", "stream", "stream_options", "temperature", "top_p", "max_tokens",
    "max_completion_tokens", "stop", "seed", "presence_penalty", "frequency_penalty", "tools", "tool_choice",
    "parallel_tool_calls", "response_format", "think", "reasoning_effort",
})


LOCAL_ONLY_FIELDS = frozenset({"think"})
EMBEDDING_FIELDS = frozenset({"model", "input", "encoding_format", "dimensions"})


def load_model_info(config_path: Path) -> dict[str, dict[str, Any]]:
    """LiteLLM 별칭마다 model_info를 돌려줍니다. location(local|external)은 꼭 있어야 합니다."""
    doc = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for m in doc.get("model_list", []):
        info = dict(m.get("model_info") or {})
        if info.get("location") not in ("local", "external"):
            raise ValueError(f"LiteLLM 별칭 {m.get('model_name')}에 model_info.location(local|external)이 없습니다")
        out[m["model_name"]] = info
    return out


def load_model_locations(config_path: Path) -> dict[str, str]:
    return {alias: info["location"] for alias, info in load_model_info(config_path).items()}


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
                 redactor: Redactor = no_redaction, glossary: Glossary | None = None,
                 external_log: JsonlWriter | None = None, no_response_format: frozenset[str] = frozenset()):
        self.locations = locations
        self.registry, self.issuer, self.audit, self.alerter = registry, issuer, audit, alerter
        self.redactor = redactor
        self.glossary = glossary or Glossary([])
        self.external_log = external_log  # contracts/events/external-request.schema.json, 평가 때만
        self.no_response_format = no_response_format  # model_info.supports_response_format: false인 별칭
        self.local_alias = next((a for a, loc in locations.items() if loc == "local"), None)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, headers=headers,
                                       timeout=httpx.Timeout(timeout, connect=5.0))
        self._timeout = timeout

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---------- 요청 해석 ----------
    def _caller(self, request: Request) -> Caller:
        request.state.caller = caller = self._read_caller(request)
        return caller

    def _read_caller(self, request: Request) -> Caller:
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
        if not isinstance(body, dict) or not isinstance(body.get("model"), str) \
                or not isinstance(body.get("messages"), list):
            raise ProblemError(422, "validation", "model과 messages(배열)가 필요합니다")
        extra = sorted(set(body) - ALLOWED_FIELDS)
        if extra:
            raise ProblemError(422, "validation", "받지 않는 필드가 있습니다", ", ".join(extra))
        return body

    # ---------- 거절 기록 ----------
    async def _guarded(self, request: Request, fn) -> Response:
        """출구가 요청을 거절하면(형식 422, 인증 401, 정책 403 등) 감사 이벤트에 이유를 남깁니다(본문은 넣지 않음)."""
        _audited.set(False)
        try:
            return await fn(request)
        except ProblemError as e:
            if not _audited.get():
                caller = getattr(request.state, "caller", None) or Caller(None, None, None)
                model = getattr(request.state, "model", None)
                detail = f"{e.status} {e.title}" + (f": {e.detail}" if e.detail else "")
                self._audit(caller, model, "denied" if e.status < 500 else "error", f"urn:problem:{e.code}",
                            detail)
            raise

    async def handle(self, request: Request) -> Response:
        return await self._guarded(request, self._handle)

    async def handle_embeddings(self, request: Request) -> Response:
        return await self._guarded(request, self._handle_embeddings)

    def _model(self, request: Request, alias: str) -> dict[str, Any]:
        """요청한 별칭으로 기록용 model을 만듭니다. 모르는 별칭이면 이름만 남기고 422를 냅니다."""
        location = self.locations.get(alias)
        if location is None:
            request.state.model = {"name": alias}
            raise ProblemError(422, "validation", "모르는 모델 별칭입니다",
                               f"{alias}. 쓸 수 있는 별칭: {', '.join(sorted(self.locations))}")
        request.state.model = model = {"name": alias, "location": location, "externalSent": False,
                                       "redactions": 0}
        return model

    # ---------- 처리 ----------
    async def _handle(self, request: Request) -> Response:
        caller = self._caller(request)
        body = await self._body(request)
        model = self._model(request, body["model"])
        location = model["location"]

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
            # think는 Ollama 전용 필드입니다. 외부 공급자는 모르는 필드를 400으로 거절하고(Anthropic 실측),
            # LiteLLM drop_params도 이 필드는 거르지 않아 gateway가 뺍니다. 추론 조절은 reasoning_effort로 합니다.
            sent = {k: v for k, v in sent.items() if k not in LOCAL_ONLY_FIELDS}
            sent, counts = self.redactor(sent)
            model["redactions"] = sum(counts.values())
            if counts:
                detail = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                self._audit(caller, model, "ok", detail=detail, kind="llm.redacted")

        if "response_format" in sent and model["name"] in self.no_response_format:
            raise ProblemError(400, "unsupported-parameter", "이 모델은 response_format(구조화 출력)을 지원하지 않습니다",
                               f"{model['name']}. 형식은 도구 호출이나 프롬프트 지시로 맞출 수 있습니다")
        if sent.get("stream"):
            return await self._stream(caller, model, before, sent)
        return await self._once(caller, model, before, sent)

    async def _handle_embeddings(self, request: Request) -> Response:
        """`POST /v1/embeddings`. 로컬 별칭만 받습니다(문서 원문을 외부로 보내지 않음). 가림은 하지 않습니다."""
        caller = self._caller(request)
        try:
            body = json.loads(await request.body())
        except ValueError:
            raise ProblemError(422, "validation", "JSON 본문이 아닙니다")
        if not isinstance(body, dict) or not isinstance(body.get("model"), str) \
                or not isinstance(body.get("input"), (str, list)):
            raise ProblemError(422, "validation", "model과 input이 필요합니다")
        extra = sorted(set(body) - EMBEDDING_FIELDS)
        if extra:
            raise ProblemError(422, "validation", "받지 않는 필드가 있습니다", ", ".join(extra))
        model = self._model(request, body["model"])
        location = model["location"]
        if location != "local":
            detail = "임베딩은 로컬 모델만 씁니다"
            self._audit(caller, model, "denied", "urn:problem:model-policy", detail)
            raise ProblemError(403, "model-policy", "모델 정책에 맞지 않습니다", detail)
        try:
            r = await self._http.post("/v1/embeddings", json=json.loads(scrub(json.dumps(body, ensure_ascii=False))))
        except httpx.HTTPError as e:
            await self._fail(caller, model, body, e)
        if r.status_code >= 500:
            await self.alerter.alert(f"LLM 프록시 오류 {r.status_code} model={model['name']}")
            self._audit(caller, model, "error", "urn:problem:llm-upstream-error", f"status {r.status_code}")
            raise ProblemError(502, "llm-upstream-error", "임베딩 호출이 실패했습니다", f"LiteLLM {r.status_code}")
        self._audit(caller, model, "ok" if r.status_code < 400 else "error",
                    None if r.status_code < 400 else f"urn:problem:llm-status-{r.status_code}")
        return Response(r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))

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

    def _mark_sent(self, caller: Caller, model: dict, sent: dict, sent_out: bool = True) -> None:
        """요청이 나갔으면 표시하고, 외부로 나갔으면 평가용 외부 요청 기록(GATEWAY_EXTERNAL_LOG)을 씁니다."""
        model["externalSent"] = model["location"] == "external" and sent_out
        if model["externalSent"] and self.external_log is not None:
            self.external_log.write({"conversationId": caller.conversation_id,
                                     "agentId": caller.agent.id if caller.agent else None,
                                     "at": now_iso(), "model": model["name"], "body": sent})

    async def _once(self, caller: Caller, model: dict, before: dict, sent: dict) -> Response:
        try:
            r = await self._http.post("/v1/chat/completions", json=sent)
        except httpx.HTTPError as e:
            await self._fail(caller, model, sent, e)
        self._mark_sent(caller, model, sent)
        if r.status_code == 501:
            self._unsupported(caller, model, before, sent, r.text)
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
            await self._fail(caller, model, sent, e)
        self._mark_sent(caller, model, sent)
        if r.status_code >= 400:
            text = (await r.aread()).decode("utf-8", "replace")
            await r.aclose()
            if r.status_code == 501:
                self._unsupported(caller, model, before, sent, text)
            if r.status_code >= 500:
                await self._upstream_error(caller, model, before, sent, r.status_code, text)
            self._egress(caller, model, before, sent, r.status_code, text)
            self._audit(caller, model, "error", f"urn:problem:llm-status-{r.status_code}")
            return Response(text, status_code=r.status_code,
                            media_type=r.headers.get("content-type", "application/json"))

        async def relay() -> AsyncIterator[bytes]:
            chunks: list[bytes] = []
            result, problem, detail = "error", "urn:problem:llm-stream-aborted", "호출한 쪽이 끊음"
            try:
                async for chunk in r.aiter_bytes():  # 압축은 풀어서 넘깁니다(content-encoding 헤더를 넘기지 않음)
                    chunks.append(chunk)
                    yield chunk
                result, problem, detail = "ok", None, None
            except httpx.HTTPError as e:
                problem, detail = "urn:problem:llm-stream-broken", type(e).__name__
                await self.alerter.alert(f"LLM 스트림 중단 model={model['name']} ({type(e).__name__})")
            finally:
                # 호출한 쪽이 끊어 생성기가 닫혀도(GeneratorExit·취소) 이미 나간 요청은 기록합니다.
                self._egress(caller, model, before, sent, r.status_code, b"".join(chunks).decode("utf-8", "replace"))
                self._audit(caller, model, result, problem, detail)
                await r.aclose()

        return StreamingResponse(relay(), status_code=r.status_code,
                                 media_type=r.headers.get("content-type", "text/event-stream"))

    # ---------- 실패·기록 ----------
    async def _fail(self, caller: Caller, model: dict, sent: dict, e: httpx.HTTPError) -> NoReturn:
        if isinstance(e, httpx.TimeoutException):
            status, code, title = 504, "llm-timeout", f"모델이 {self._timeout:g}초 안에 답하지 않았습니다"
        else:
            status, code, title = 502, "llm-unavailable", "LLM 프록시에 연결하지 못했습니다"
        # 연결 전 실패가 아니면(읽기 시간 초과 등) 요청은 이미 나갔다고 봅니다.
        self._mark_sent(caller, model, sent, sent_out=not isinstance(e, httpx.ConnectError))
        await self.alerter.alert(f"{title} model={model['name']} ({type(e).__name__})")
        self._audit(caller, model, "error", f"urn:problem:{code}", type(e).__name__)
        raise ProblemError(status, code, title)

    def _unsupported(self, caller: Caller, model: dict, before: dict, sent: dict, text: str) -> NoReturn:
        """LiteLLM 501은 장애가 아니라 모델·실행기가 기능을 지원하지 않는 것입니다(예: Ollama MLX 실행기의 구조화 출력).
        알림을 보내지 않고 400으로 이유를 돌려줍니다."""
        try:
            reason = str(json.loads(text)["error"]["message"]).split("\n")[0][:200]
        except (ValueError, KeyError, TypeError):
            reason = "모델이 이 요청 기능을 지원하지 않습니다"
        self._egress(caller, model, before, sent, 501, text)
        self._audit(caller, model, "denied", "urn:problem:unsupported-parameter", f"LiteLLM 501: {scrub(reason)}")
        raise ProblemError(400, "unsupported-parameter", "모델이 이 요청 기능을 지원하지 않습니다", scrub(reason))

    async def _upstream_error(self, caller: Caller, model: dict, before: dict, sent: dict,
                              status: int, text: str) -> NoReturn:
        await self.alerter.alert(f"LLM 프록시 오류 {status} model={model['name']}")
        self._egress(caller, model, before, sent, status, text)
        self._audit(caller, model, "error", "urn:problem:llm-upstream-error", f"status {status}")
        raise ProblemError(502, "llm-upstream-error", "모델 호출이 실패했습니다", f"LiteLLM {status}")

    def _audit(self, caller: Caller, model: dict, result: str, problem_type: str | None = None,
               detail: str | None = None, kind: str = "llm.request") -> None:
        if kind == "llm.request":
            _audited.set(True)
        self.audit.event(kind, employee_id=caller.employee_id,
                         agent_id=caller.agent.id if caller.agent else None, via_token=caller.via_token,
                         conversation_id=caller.conversation_id,
                         model=dict(model) if model is not None else None, result=result,
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

