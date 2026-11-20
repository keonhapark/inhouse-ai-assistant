"""2단계 등록부(재무·구매자재 포함)에서의 입구 라우터. 문장은 직접 썼고(평가 셋 아님) LLM 응답은 녹화본으로 돕니다.

LLM 라우터와 키워드 기준선을 같은 문장으로 돌려 정답 비율을 비교합니다. 비율은 시험 출력(-s)에 찍습니다.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from agent_runtime.llm import ChatClient, LLMSettings
from agent_runtime.registry import Registry, Requester
from agent_runtime.router import Router
from tests.conftest import PACK_DIR, RECORDED_MODEL, RECORDINGS
from tests.llm_cassette import Cassette

ME = Requester("E0016", "finance", "staff", ("employee",))

CASES = [
    # 재무
    ("지난주 부산 출장 숙박비 12만 원 정산 올려 줘", "finance"),
    ("법인카드로 결제한 회식비 처리해야 해", "finance"),
    ("해외 출장 일비 기준이 어떻게 돼?", "finance"),
    ("어제 택시비 영수증 있는데 어떻게 청구해?", "finance"),
    # 구매자재
    ("볼트 M8 500개 발주 넣어 줘", "procurement"),
    ("새 모니터 3대 구매 요청하려고 해", "procurement"),
    # 녹화한 모델 답이 이유에는 구매 담당이라고 쓰고 agentId는 none이었습니다(알려진 오답).
    pytest.param("견적 두 군데 받아야 하는 금액 기준이 뭐야?", "procurement",
                 marks=pytest.mark.xfail(strict=True, reason="녹화한 모델 답이 agentId none")),
    ("자재 단가가 올랐는데 구매 요청 다시 올려야 해?", "procurement"),
    # 인사
    ("다음 주 수요일 반차 쓸게", "hr"),
    ("내 연차 며칠 남았어?", "hr"),
    ("휴가 동안 결재를 박 과장한테 맡겨 줘", "hr"),
    # 전사 비서
    ("내일 오전 10시에 6명 회의실 잡아 줘", "assistant"),
    ("3층 회의실 오후에 비어 있어?", "assistant"),
    ("사내 메신저 비밀번호는 어디서 바꿔?", "assistant"),
]


@pytest.fixture(scope="module")
def reg2() -> Registry:
    return Registry.load(PACK_DIR, stage=2)


@pytest.fixture(scope="module")
def cassette2() -> Iterator[Cassette]:
    c = Cassette.from_env(RECORDINGS / "router_llm_stage2.json")
    yield c
    c.save()


@pytest.fixture(scope="module")
def chat2(cassette2: Cassette) -> ChatClient:
    settings = LLMSettings.from_env() if cassette2.record else LLMSettings(base_url="http://recorded.invalid/v1",
                                                                          model=RECORDED_MODEL)
    return ChatClient(settings, transport=cassette2)


@pytest.mark.parametrize(("message", "expected"), CASES)
def test_llm_routes_stage2(reg2: Registry, chat2: ChatClient, message: str, expected: str) -> None:
    # fallback 에이전트가 정답이면 모델이 고르지 못해 fallback으로 가도 결과는 같습니다.
    assert Router(reg2, chat2).route(message, ME).agent_id == expected


def test_llm_vs_keyword_on_same_cases(reg2: Registry, chat2: ChatClient) -> None:
    llm = Router(reg2, chat2)
    kw = Router(reg2, None)
    pairs = [(c.values[0], c.values[1]) if hasattr(c, "values") else c for c in CASES]
    llm_ok = sum(llm.route(m, ME).agent_id == e for m, e in pairs)
    kw_ok = sum(kw.route(m, ME, "keyword").agent_id == e for m, e in pairs)
    print(f"\n라우터 2단계 문장 {len(pairs)}개: LLM {llm_ok}, 키워드 {kw_ok}")
    # 녹화본 기준 값입니다. 프롬프트·등록부를 바꿔 다시 녹화하면 함께 고칩니다.
    assert (llm_ok, kw_ok) == (13, 13)
