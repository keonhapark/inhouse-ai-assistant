"""LLM 출구. rag·agent의 OpenAI 호환 요청(`POST /v1/chat/completions`)을 받아 정책을 확인하고 LiteLLM 프록시로 넘깁니다.

순서
1. `X-Delegation-Token`이 있으면 이 gateway가 서명한 토큰인지 확인하고 `agt`로 에이전트를 찾습니다.
2. `model`은 LiteLLM 설정의 별칭만 받습니다. 별칭마다 `model_info.location`(local·external)이 있습니다.
3. 정책: 에이전트 model_policy가 local_only이거나 위임 토큰이 없으면 외부 별칭을 막습니다(403 model-policy).
4. 본문에서 토큰 모양 문자열을 가립니다. 토큰 헤더는 넘기지 않습니다.
5. 외부 별칭이면 사내 용어 사전과 업무 주제(gateway/confidential.py, #304)로 기밀을 판정해 차단(403 confidential)하거나 로컬 별칭으로
   돌립니다. 그래도 외부로 나가면 한국어 개인정보를 가립니다(gateway/pii.py). 둘 다 감사 이벤트 llm.redacted를 남깁니다.
   로컬 모델로 가는 요청은 가리지 않습니다.
6. 외부로 나간 요청은 가림 뒤 본문·가린 자리·응답을 egress.jsonl에(가림 전 원문은 저장하지 않음), 모든 요청은 감사 이벤트 llm.request로 남깁니다.
   이미지(`image_url`)가 든 요청은 2·3단계 전에 형식·크기를 확인하고(gateway/vision.py), 요청한 별칭·정책과 관계없이
   로컬 비전 별칭(model_info.vision)으로만 보냅니다. 감사에는 이미지 본문 대신 형식·크기·해시를 남깁니다(#261).
   GATEWAY_LOCAL_REASONING_EFFORT를 주면 외부 별칭 요청을 로컬로 돌린 호출(이미지·팩 금지·기밀 판정·비용 상한·외부 장애 폴백)에
   reasoning_effort·think가 없을 때 그 값을 채웁니다(#427). 기본은 채우지 않고 시간 제한을 120초로 둡니다(#536, 결정 0008).
7. 시간 초과(504)·연결 실패(502)·LiteLLM 5xx(502)는 실패 알림을 보냅니다.
8. 의미 캐시(gateway/cache.py, #465)를 켰으면 정책·기밀 판정·가림이 끝난 본문으로 찾고, 적중하면 LLM을 부르지 않습니다(X-Cache).
"""

from __future__ import annotations

import json
import logging
import uuid
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
from gateway.budgets import BudgetLedger
from gateway.cache import Probe, SemanticCache
from gateway.confidential import Glossary
from gateway.problems import ProblemError
from gateway.redact import scrub
from gateway.registry import AgentEntry, Registry
from gateway.tokens import DelegationTokenIssuer
from gateway.vision import has_inline_image, inspect_images

log = logging.getLogger(__name__)

TOKEN_HEADER = "x-delegation-token"

# 이 요청에서 감사 이벤트를 이미 남겼는지. 거절 사유를 따로 남긴 경로(정책·기밀·장애)는 한 번만 기록합니다.
_audited: ContextVar[bool] = ContextVar("egress_audited", default=False)

# 가림 단계: 본문을 받아 (보낼 본문, 개체 종류별 가린 개수, 가린 자리)를 돌려줍니다(gateway/pii.py).
Redactor = Callable[[dict[str, Any]], tuple[dict[str, Any], Counter, list[dict[str, Any]]]]


def no_redaction(body: dict[str, Any]) -> tuple[dict[str, Any], Counter, list[dict[str, Any]]]:
    return body, Counter(), []


# LiteLLM에 넘기는 본문 필드. 그 밖의 필드(fallbacks, api_base, metadata, mock_response 등)는 정책 검사를 건너뛰어
# 다른 모델로 보내게 만들 수 있어 422로 거절합니다.
ALLOWED_FIELDS = frozenset({
    "model", "messages", "stream", "stream_options", "temperature", "top_p", "max_tokens",
    "max_completion_tokens", "stop", "seed", "presence_penalty", "frequency_penalty", "tools", "tool_choice",
    "parallel_tool_calls", "response_format", "think", "reasoning_effort",
})


LOCAL_ONLY_FIELDS = frozenset({"think"})
EVAL_TOOLCALL_PURPOSE = "eval-toolcall"
# 외부 장애로 보고 로컬로 폴백하는 오류(시간 초과, 연결 실패, LiteLLM 5xx). 미지원(400)·정책 거절은 폴백하지 않습니다.
FALLBACK_CODES = frozenset({"llm-timeout", "llm-unavailable", "llm-upstream-error"})
EMBED_TIMEOUT_SECONDS = 2.0  # 의미 캐시 임베딩(#465)
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


def load_provider_models(config_path: Path) -> dict[str, str]:
    """LiteLLM 별칭 → 실제 모델 이름(litellm_params.model, 예: anthropic/claude-haiku-5-5)."""
    doc = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return {m["model_name"]: m["litellm_params"]["model"] for m in doc.get("model_list", [])
            if (m.get("litellm_params") or {}).get("model")}


def load_model_locations(config_path: Path) -> dict[str, str]:
    return {alias: info["location"] for alias, info in load_model_info(config_path).items()}


@dataclass(frozen=True)
class Guards:
    pii: str            # korean(한국 인식기) | baseline(Presidio 기성 기본값) | off
    glossary: bool      # 사내 용어 기밀 판정
    local_enforce: bool  # 에이전트 정책의 로컬 강제(위임 토큰 없는 호출의 외부 금지 포함)


# 평가 조건별 출구 장치(contracts/eval/conditions.md). 조건이 없는 대화(운영)는 full입니다.
CONDITION_GUARDS = {
    "no_guard": Guards("off", False, False),
    "write_blocked": Guards("korean", True, True),
    "approve_all": Guards("korean", True, True),
    "baseline_tools": Guards("baseline", False, False),
    "full": Guards("korean", True, True),
}


class ModelUsage:
    """대화 차례마다 출구가 실제로 보낸 모델을 모읍니다(위임 토큰의 cid 기준).

    채팅 흐름이 agent를 부르기 전에 begin, 끝난 뒤 take로 꺼내 ChatEvent model(name, location)에 씁니다.
    begin하지 않은 대화(rag의 대화 밖 호출 등)는 모으지 않습니다.
    """

    def __init__(self) -> None:
        self._turns: dict[str, list[tuple[str, str]]] = {}

    def begin(self, conversation_id: str) -> None:
        self._turns[conversation_id] = []

    def record(self, conversation_id: str | None, alias: str, location: str) -> None:
        if conversation_id in self._turns:
            self._turns[conversation_id].append((alias, location))

    def take(self, conversation_id: str) -> dict[str, str] | None:
        """한 번이라도 외부로 나갔으면 external(그 별칭), 아니면 마지막으로 쓴 로컬 별칭. 쓴 모델이 없으면 None."""
        used = self._turns.pop(conversation_id, [])
        if not used:
            return None
        name, location = next((u for u in reversed(used) if u[1] == "external"), used[-1])
        return {"name": name, "location": location}


def public_model(model: dict | None) -> dict | None:
    """감사 이벤트용 model. 밑줄로 시작하는 내부 키(가린 자리 등)는 뺍니다."""
    return None if model is None else {k: v for k, v in model.items() if not k.startswith("_")}


def egress_headers(model: dict) -> dict[str, str]:
    """실제로 보낸 별칭과 위치(contracts/openapi/gateway.yaml). 기밀·비용 상한·폴백으로 로컬로 바뀌면 요청과 다릅니다."""
    return {"X-Egress-Model": model["name"], "X-Egress-Location": model["location"]}


def response_cost(headers: httpx.Headers) -> float | None:
    """LiteLLM 프록시가 응답 머리글로 주는 이 요청의 비용(달러)."""
    try:
        return float(headers["x-litellm-response-cost"])
    except (KeyError, ValueError):
        return None


def response_usage(text: str) -> dict[str, int] | None:
    """응답 본문(JSON 또는 SSE)에서 usage의 prompt_tokens·completion_tokens를 꺼냅니다."""
    candidates: list[str] = [text]
    if text.lstrip().startswith("data:"):
        candidates = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")][::-1]
    for c in candidates:
        try:
            u = json.loads(c).get("usage")
        except (ValueError, AttributeError):
            continue
        if isinstance(u, dict):
            return {k: u[k] for k in ("prompt_tokens", "completion_tokens") if isinstance(u.get(k), int)}
    return None


@dataclass(frozen=True)
class Caller:
    employee_id: str | None
    agent: AgentEntry | None
    conversation_id: str | None
    token_id: str | None = None  # 위임 토큰 jti. 감사 이벤트 actor.delegationTokenId로 발급 기록과 잇습니다
    scopes: tuple[str, ...] = ()      # 위임 토큰 scopes·doc_scopes. 의미 캐시 키의 권한 범위(#465)
    doc_scopes: tuple[str, ...] = ()

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
        return f"{caller.agent.name} 에이전트는 외부 모델을 쓰지 않도록 설정돼 있습니다"
    return None


class Egress:
    def __init__(self, *, base_url: str, locations: dict[str, str], registry: Registry,
                 issuer: DelegationTokenIssuer, audit: AuditLog, alerter: Alerter, timeout: float,
                 api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 redactor: Redactor = no_redaction, glossary: Glossary | None = None,
                 external_log: JsonlWriter | None = None, no_response_format: frozenset[str] = frozenset(),
                 baseline_redactor: Redactor = no_redaction,
                 drop_params: dict[str, frozenset[str]] | None = None,
                 condition_of: Callable[[str | None], str | None] = lambda _cid: None,
                 budget: BudgetLedger | None = None,
                 unit_of: Callable[[str | None], str | None] = lambda _cid: None,
                 prices: dict[str, tuple[float, float]] | None = None,
                 provider_models: dict[str, str] | None = None,
                 vision_alias: str | None = None, eval_toolcall: bool = False,
                 local_reasoning_effort: str | None = None,
                 embed_alias: str | None = None):
        self.locations = locations
        # 외부 별칭 요청을 로컬로 돌릴 때 채울 reasoning_effort(#427). None이면 채우지 않습니다.
        self.local_reasoning_effort = local_reasoning_effort
        # GATEWAY_EVAL_TOOLCALL=1: 토큰 없는 외부 호출을 받습니다(#268, 도구 호출 측정의 외부 기준). 측정 데이터는 지어낸 것입니다.
        # GATEWAY_EVAL_MODE와 따로 둡니다(#294): 정상·확인 셋 실행에서 열리면 대화 밖 외부 전송이 판정에서 빠집니다.
        self.eval_toolcall = eval_toolcall
        self.vision_alias = vision_alias  # 이미지 입력을 보낼 로컬 별칭(model_info.vision). 없으면 이미지를 받지 않음
        self.registry, self.issuer, self.audit, self.alerter = registry, issuer, audit, alerter
        self.redactor = redactor
        self.glossary = glossary or Glossary([])
        self.external_log = external_log  # contracts/events/external-request.schema.json, 평가 때만
        self.usage = ModelUsage()
        self.baseline_redactor = baseline_redactor
        self.drop_params = drop_params or {}  # 별칭별로 보내기 전에 뺄 필드(model_info.drop_params)
        # 위임 토큰 cid로 대화의 평가 조건을 찾습니다(채팅 흐름이 기억). 운영에서는 늘 None → full.
        self.condition_of = condition_of
        self.budget = budget
        self.unit_of = unit_of  # 위임 토큰 cid → 요청자 소속 부서(채팅 흐름이 기억). 모르면 None
        self.provider_models = provider_models or {}  # 별칭 → 실제 모델 이름(외부 요청 기록 model)
        self.prices = prices or {}  # 별칭 → (입력, 출력) USD/토큰. 비용 머리글이 없을 때(스트림) 씁니다
        self.no_response_format = no_response_format  # model_info.supports_response_format: false인 별칭
        self.local_alias = next((a for a, loc in locations.items() if loc == "local"), None)
        # 평가 대화의 별칭 바꿔 끼우기(X-Eval-Model-Override, #346): cid → {"local": 별칭, "external": 별칭}
        self.override_of: Callable[[str | None], dict[str, str]] = lambda _cid: {}
        # 의미 캐시(#465). None이면 끔(기본, 평가 모드). main이 GATEWAY_SEMANTIC_CACHE=1일 때 붙입니다.
        self.cache: SemanticCache | None = None
        self.embed_alias = embed_alias  # 의미 캐시 임베딩에 쓸 로컬 별칭(model_info.mode: embedding)
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
        return Caller(claims["sub"], agent, claims["cid"], claims.get("jti"),
                      tuple(sorted(claims.get("scopes") or ())), tuple(sorted(claims.get("doc_scopes") or ())))

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
        requested = self.locations.get(body["model"])  # 요청한 별칭의 위치. 로컬로 돌렸는지 가를 때 씁니다(#427)
        images = inspect_images(body)
        note = None
        if images:
            # 영수증 등 이미지에는 카드 번호·사업자번호가 그대로 있어 가림이 듣지 않습니다. 외부로 보내지 않습니다.
            if self.vision_alias is None or self.locations.get(self.vision_alias) != "local":
                raise ProblemError(400, "unsupported-parameter", "이미지를 읽을 로컬 모델이 없습니다")
            note = (f"이미지 {len(images)}장({', '.join(i.describe() for i in images)}): "
                    f"요청 별칭 {body['model']} 대신 {self.vision_alias}")
            body = {**body, "model": self.vision_alias}
        else:
            swapped = self._swap(caller, body["model"])
            if swapped != body["model"]:
                note = f"평가 별칭 바꿔 끼움: {body['model']} 대신 {swapped}"
                body = {**body, "model": swapped}
        if self.registry.pack_local_only and self.locations.get(body["model"]) == "external":
            # 팩 단위 외부 LLM 금지(#384, 망분리 흉내). 평가 조건·에이전트 정책·별칭 바꿔 끼우기보다 앞서 봅니다.
            # 위임 토큰 호출은 에이전트가 팩 항목을 몰라도 대화가 깨지지 않게 로컬로 돌리고,
            # 토큰 없는 호출(도구 호출 측정 등)은 측정이 몰래 로컬로 바뀌지 않게 거절합니다.
            local = self._local_for(caller) if caller.agent is not None else None
            if local is None:
                request.state.model = {"name": body["model"]}
                raise ProblemError(403, "model-policy", "모델 정책에 맞지 않습니다", "이 팩은 외부 LLM을 쓰지 않습니다")
            note = (f"{note}; " if note else "") + f"팩 외부 LLM 금지: {body['model']} 대신 {local}"
            body = {**body, "model": local}
        model = self._model(request, body["model"])
        location = model["location"]

        guards = CONDITION_GUARDS[self.condition_of(caller.conversation_id) or "full"]
        denial = policy_denial(caller, location) if guards.local_enforce else None
        if denial and caller.agent is None and self.eval_toolcall:
            # 평가 모드에서만 엽니다. 가림·기밀 판정·외부 기록은 그대로 거치고, 감사에 목적을 남겨 운영 호출과 가릅니다.
            denial = None
            note = f"purpose={EVAL_TOOLCALL_PURPOSE}: 평가 모드의 토큰 없는 외부 호출"
        if denial:
            self._audit(caller, model, "denied", "urn:problem:model-policy", denial)
            raise ProblemError(403, "model-policy", "모델 정책에 맞지 않습니다", denial)

        # 토큰 모양 문자열은 어떤 모델에도 보내지 않습니다. JWT 문자에는 따옴표가 없어 JSON 문자열째 가려도 됩니다.
        before = json.loads(scrub(json.dumps(body, ensure_ascii=False)))
        sent = before
        if location == "external" and guards.glossary:
            sent = self._confidential(caller, model, before)
        # 비용 상한도 정책 장치라, 로컬 강제를 끄는 평가 조건(no_guard·baseline_tools)에서는 같이 끕니다.
        if (model["location"] == "external" and guards.local_enforce and self.budget is not None
                and self.local_alias is not None):
            over = self.budget.over(caller.agent.id if caller.agent else None,
                                    self.unit_of(caller.conversation_id))
            if over is not None:
                # 상한을 넘었으면 이 요청부터 로컬로 내립니다(가림 전 본문, 로컬은 사내에서 돎).
                note = (f"비용 상한 초과({over.kind} {over.id} ${over.spent:.6g}/${over.limit:.6g})로 로컬 모델로 내림")
                local = self._local_for(caller)
                model.update(name=local, location="local")
                sent = {**sent, "model": local}
        if model["location"] == "external":
            if has_inline_image(sent):
                # 글 속 data URL은 가림(pii.py)이 건드리지 않아 그대로 나가고 기록에도 남습니다(#261).
                raise ProblemError(422, "validation", "이미지는 image_url 부분으로만 보낼 수 있습니다",
                                   "글 속에 이미지 data URL이 있습니다")
            # think는 Ollama 전용 필드입니다. 외부 공급자는 모르는 필드를 400으로 거절하고(Anthropic 실측),
            # LiteLLM drop_params도 이 필드는 거르지 않아 gateway가 뺍니다. 추론 조절은 reasoning_effort로 합니다.
            sent = {k: v for k, v in sent.items() if k not in LOCAL_ONLY_FIELDS}
            redactor = {"korean": self.redactor, "baseline": self.baseline_redactor,
                        "off": no_redaction}[guards.pii]
            sent, counts, spans = redactor(sent)
            model["_spans"] = spans  # 운영 기록용(가린 자리). 감사 이벤트에는 넣지 않습니다
            model["redactions"] = sum(counts.values())
            if counts:
                detail = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                self._audit(caller, model, "ok", detail=detail, kind="llm.redacted")

        if requested == "external" and model["location"] == "local":
            sent, note = self._quiet_local(model["name"], sent, note)
        drop = self.drop_params.get(model["name"], frozenset())
        if drop & set(sent):
            sent = {k: v for k, v in sent.items() if k not in drop}
        if "response_format" in sent and model["name"] in self.no_response_format:
            raise ProblemError(400, "unsupported-parameter", "이 모델은 response_format(구조화 출력)을 지원하지 않습니다",
                               f"{model['name']}. 형식은 도구 호출이나 프롬프트 지시로 맞출 수 있습니다")
        probe = await self._cache_probe(caller, model, sent, bool(images))
        if probe is not None:
            hit = self.cache.lookup(probe)
            if hit is not None:
                # LLM을 부르지 않으므로 외부 전송·비용·외부 기록이 없습니다(#485). 감사에는 cacheHit로 남겨 운영 지표의 LLM 요청 수에서
                # 빼고, 대화 사용 집계(ChatEvent model)에는 넣지 않습니다. 머리글의 별칭·위치는 그 답을 만든 별칭입니다(계약 #475).
                model["cacheHit"] = True
                note = (f"{note}; " if note else "") + f"의미 캐시 적중(유사도 {hit.similarity:.3f})"
                self._audit(caller, model, "ok", None, note)
                return Response(hit.entry.content, status_code=200, media_type=hit.entry.media_type,
                                headers={**egress_headers(model), "X-Cache": "hit"})
        try:
            response = await self._dispatch(caller, model, before, sent, note=note)
            if probe is not None:
                response.headers["X-Cache"] = "miss"
                if response.status_code == 200:
                    self.cache.store(probe, response.body, response.media_type or "application/json")
            return response
        except ProblemError as e:
            fallback = self._fallback_body(model, before, e, self._local_for(caller))
            if fallback is None:
                raise
            # 외부 장애는 위에서 알림·감사(error)를 남겼습니다. 같은 요청을 로컬 별칭으로 한 번 다시 보냅니다.
            local = {"name": self._local_for(caller), "location": "local", "externalSent": False, "redactions": 0}
            request.state.model = local
            note = (f"{note}; " if note else "") + f"외부 장애({e.code})로 로컬 폴백"
            fallback, note = self._quiet_local(local["name"], fallback, note)
            return await self._dispatch(caller, local, before, fallback, note=note)

    async def _cache_probe(self, caller: Caller, model: dict, sent: dict, has_images: bool) -> Probe | None:
        """의미 캐시 키. 위임 토큰이 있고 스트림·이미지·평가 조건이 아닌 호출만. 임베딩이 실패하면 캐시 없이 갑니다."""
        if (self.cache is None or self.embed_alias is None or caller.agent is None or sent.get("stream") or has_images
                or self.condition_of(caller.conversation_id) is not None):
            return None
        # 요청자(sub)를 넣어 사람마다 따로 둡니다(#484). 권한이 같아도 이름·사유만 다른 문장이 의미상 같게 잡힐 수 있습니다.
        scope = (caller.employee_id, caller.agent.id, caller.scopes, caller.doc_scopes, model["name"])
        try:
            return await self.cache.probe(scope, sent)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as e:
            log.warning("의미 캐시 임베딩 실패(%s), 캐시 없이 보냅니다", type(e).__name__)
            return None

    async def embed_text(self, text: str) -> list[float]:
        """의미 캐시용 임베딩(로컬 임베딩 별칭). gateway 내부 호출이라 감사 이벤트를 남기지 않습니다."""
        # 임베딩이 멈춰도 모든 요청이 LLM 시간 제한만큼 기다리지 않게 짧게 끊고 캐시 없이 갑니다.
        r = await self._http.post("/v1/embeddings", json={"model": self.embed_alias, "input": text},
                                  timeout=httpx.Timeout(EMBED_TIMEOUT_SECONDS))
        r.raise_for_status()
        return [float(x) for x in r.json()["data"][0]["embedding"]]

    def _quiet_local(self, alias: str, sent: dict, note: str | None) -> tuple[dict, str | None]:
        """외부 별칭 요청을 로컬로 돌린 본문에 reasoning_effort를 채우고 감사 detail에 적습니다(#427).

        호출한 쪽은 외부 모델을 기대해 생각 단계를 정하지 않았을 수 있고, 로컬 qwen3.5:9b는 생각 모드가 기본이라 길게 생각하다
        시간 제한(LLM_TIMEOUT_SECONDS)을 넘깁니다. 호출한 쪽이 reasoning_effort나 think를 정했거나 이 별칭이 reasoning_effort를
        빼는 별칭(model_info.drop_params)이면 그대로 둡니다.
        """
        effort = self.local_reasoning_effort
        if (effort is None or "reasoning_effort" in sent or "think" in sent
                or "reasoning_effort" in self.drop_params.get(alias, frozenset())):
            return sent, note
        return {**sent, "reasoning_effort": effort}, (f"{note}; " if note else "") + f"생각 단계 끔(reasoning_effort={effort})"

    def _swap(self, caller: Caller, alias: str) -> str:
        """평가 대화의 별칭 바꿔 끼우기. 위치가 같은 별칭으로만 바꿉니다(정책·가림이 그대로 적용되게).

        로컬 업무 별칭(이미지 전용 별칭이 아닌 로컬 별칭)은 local 대상으로, 외부 별칭은 external 대상으로 바꿉니다.
        토큰 없는 호출(입구 라우터 등)은 대화가 없어 바꾸지 않습니다.
        """
        override = self.override_of(caller.conversation_id) if caller.conversation_id else {}
        location = self.locations.get(alias)
        if not override or location is None or alias == self.vision_alias:
            return alias
        target = override.get(location)
        return target if target and self.locations.get(target) == location else alias

    def _local_for(self, caller: Caller) -> str | None:
        """기밀 판정·비용 상한·외부 장애로 로컬로 돌릴 때 쓸 별칭(평가 대화면 바꿔 끼운 것)."""
        return self._swap(caller, self.local_alias) if self.local_alias else None

    async def _dispatch(self, caller: Caller, model: dict, before: dict, sent: dict,
                        note: str | None = None) -> Response:
        if sent.get("stream"):
            return await self._stream(caller, model, before, sent, note)
        return await self._once(caller, model, before, sent, note)

    def _fallback_body(self, model: dict, before: dict, e: ProblemError, local: str | None) -> dict | None:
        """외부 장애(시간 초과·연결 실패·5xx)면 로컬로 보낼 본문을, 폴백할 수 없으면 None을 돌려줍니다.

        로컬 모델은 사내에서 돌므로 가림 전 본문(토큰 모양만 가린 것)을 보냅니다. 로컬이 지원하지 않는
        response_format 요청은 폴백하지 않고 원래 오류를 돌려줍니다.
        """
        if model["location"] != "external" or e.code not in FALLBACK_CODES or local is None:
            return None
        if "response_format" in before and local in self.no_response_format:
            return None
        return {**before, "model": local}

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
            await self._fail(caller, model, body, body, e)
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
        found = ", ".join(([f"기밀 용어 {verdict.hits}개"] if verdict.hits else [])
                          + ([f"업무 주제 {' '.join(verdict.topics)}"] if verdict.topics else []))
        if verdict.action == "block" or self.local_alias is None:
            detail = f"{found}: 차단"
            self._audit(caller, model, "denied", "urn:problem:confidential", detail)
            raise ProblemError(403, "confidential", "사내 기밀 정보가 있어 외부 AI로 보내지 않았습니다.",
                               f"{verdict.reason}. 기밀 내용을 빼고 다시 보내 주세요.")
        self._audit(caller, model, "ok", detail=f"{found}: 로컬 모델로 돌림", kind="llm.redacted")
        local = self._local_for(caller)
        model.update(name=local, location="local")
        return {**body, "model": local}

    def _mark_sent(self, caller: Caller, model: dict, sent: dict, sent_out: bool = True) -> None:
        """요청이 나갔는지 표시하고 차례별 사용 모델에 더합니다. 외부 요청 기록은 응답을 받은 뒤(_egress·_fail) 씁니다."""
        model["externalSent"] = model["location"] == "external" and sent_out
        if sent_out:
            self.usage.record(caller.conversation_id, model["name"], model["location"])

    async def _once(self, caller: Caller, model: dict, before: dict, sent: dict,
                    note: str | None = None) -> Response:
        try:
            r = await self._http.post("/v1/chat/completions", json=sent)
        except httpx.HTTPError as e:
            await self._fail(caller, model, before, sent, e)
        self._mark_sent(caller, model, sent)
        if r.status_code == 501:
            self._unsupported(caller, model, before, sent, r.text)
        if r.status_code >= 500:
            await self._upstream_error(caller, model, before, sent, r.status_code, r.text)
        self._egress(caller, model, before, sent, r.status_code, r.text, response_cost(r.headers))
        self._audit(caller, model, "ok" if r.status_code < 400 else "error",
                    None if r.status_code < 400 else f"urn:problem:llm-status-{r.status_code}", note)
        return Response(r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"), headers=egress_headers(model))

    async def _stream(self, caller: Caller, model: dict, before: dict, sent: dict,
                      note: str | None = None) -> Response:
        req = self._http.build_request("POST", "/v1/chat/completions", json=sent)
        try:
            r = await self._http.send(req, stream=True)
        except httpx.HTTPError as e:
            await self._fail(caller, model, before, sent, e)
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
                result, problem, detail = "ok", None, note
            except httpx.HTTPError as e:
                problem, detail = "urn:problem:llm-stream-broken", type(e).__name__
                await self.alerter.alert(f"LLM 스트림 중단 model={model['name']} ({type(e).__name__})")
            finally:
                # 호출한 쪽이 끊어 생성기가 닫혀도(GeneratorExit·취소) 이미 나간 요청은 기록합니다.
                self._egress(caller, model, before, sent, r.status_code, b"".join(chunks).decode("utf-8", "replace"),
                             response_cost(r.headers))
                self._audit(caller, model, result, problem, detail)
                await r.aclose()

        return StreamingResponse(relay(), status_code=r.status_code,
                                 media_type=r.headers.get("content-type", "text/event-stream"),
                                 headers=egress_headers(model))

    # ---------- 실패·기록 ----------
    async def _fail(self, caller: Caller, model: dict, before: dict, sent: dict, e: httpx.HTTPError) -> NoReturn:
        if isinstance(e, httpx.TimeoutException):
            status, code, title = 504, "llm-timeout", f"모델이 {self._timeout:g}초 안에 답하지 않았습니다"
        else:
            status, code, title = 502, "llm-unavailable", "LLM 프록시에 연결하지 못했습니다"
        # 연결 전 실패가 아니면(읽기 시간 초과 등) 요청은 이미 나갔다고 봅니다.
        self._mark_sent(caller, model, sent, sent_out=not isinstance(e, httpx.ConnectError))
        # 이미 나간 외부 요청은 응답이 없어도 외부 전송 기록(가림 뒤 본문)을 남깁니다(#165).
        # 연결 전 실패(ConnectError)는 나가지 않았으므로 남기지 않습니다.
        if model["externalSent"]:
            self._egress(caller, model, before, sent, status, "")
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
                         model=public_model(model), result=result,
                         problem_type=problem_type, detail=detail, delegation_token_id=caller.token_id,
                         channel="agent" if caller.via_token else None)

    def _estimate_cost(self, alias: str, usage: dict[str, int] | None) -> float | None:
        """LiteLLM 비용 머리글이 없을 때(스트림) 별칭 단가와 usage로 계산합니다. 모르면 None."""
        price = self.prices.get(alias)
        if price is None or not usage:
            return None
        return usage.get("prompt_tokens", 0) * price[0] + usage.get("completion_tokens", 0) * price[1]

    def _external_record(self, caller: Caller, model: dict, sent: dict, response: str | None,
                         cost: float | None) -> None:
        """평가용 외부 요청 기록(GATEWAY_EXTERNAL_LOG, contracts/events/external-request.schema.json)."""
        if self.external_log is None:
            return
        rec: dict[str, Any] = {"conversationId": caller.conversation_id,
                               "agentId": caller.agent.id if caller.agent else None,
                               "at": now_iso(), "model": self.provider_models.get(model["name"], model["name"]),
                               "body": sent, "costUsd": cost}
        usage = response_usage(response) if response else None
        if usage is not None:
            rec["usage"] = usage
        self.external_log.write(rec)

    def _egress(self, caller: Caller, model: dict, before: dict, sent: dict, status: int, response: str,
                cost: float | None = None) -> None:
        if model["location"] != "external":
            return
        if model["externalSent"]:
            if cost is None:
                cost = self._estimate_cost(model["name"], response_usage(response) if response else None)
            if self.budget is not None:
                self.budget.add(caller.agent.id if caller.agent else None, self.unit_of(caller.conversation_id), cost)
            self._external_record(caller, model, sent, response, cost)
        usage = response_usage(response) if response else None
        self.audit.egress.write({
            # 가림 전 원문은 저장하지 않습니다(contracts/openapi/gateway.yaml /ops/egress). 가린 자리만 남깁니다.
            "recordId": "egr_" + uuid.uuid4().hex,
            "occurredAt": now_iso(),
            "employeeId": caller.employee_id,
            "agentId": caller.agent.id if caller.agent else None,
            "conversationId": caller.conversation_id,
            "model": model["name"],
            "providerModel": self.provider_models.get(model["name"]),
            "redactions": model["redactions"],
            "redactionSpans": model.get("_spans", []),
            "requestSent": sent,
            "status": status,
            "usage": usage,
            "costUsd": cost,
            "response": scrub(response),
        })

