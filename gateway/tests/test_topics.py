"""업무 주제(팩 glossary topics)로 인사·근태 정보를 로컬로 강제합니다(#304, #308 두 번째 방어선)."""

import json

import pytest

from gateway.confidential import Glossary

from .conftest import PACK
from .test_egress import _agent_ids, _audit, token_for  # noqa: F401  (픽스처)

# #86 full 조건 사고 6건(인사 요청이 전사 비서로 가서 외부로 나감)의 사용자 문장
INCIDENTS = [
    "2027년 3월 11일 병가 하루 신청해 줘. 감기가 심해서요.",
    "2027년 3월 8일부터 3월 12일까지 출장이라 휴가 결재를 이승현 님에게 맡겨 줘.",
    "대결 기간 상한 확인하고 2027년 4월 5일부터 4월 9일까지 휴가 결재를 이준호 님에게 맡겨 줘.",
    "2027년 3월 8일부터 3월 19일까지 장기 출장이라 모든 결재를 최정남 님에게 맡겨 줘.",
    "2027년 3월 22일부터 24일까지 경비 결재를 200만 원 한도로 김건우 님에게 맡겨 줘.",
    "2027년 3월 29일부터 4월 9일까지 휴가 결재를 김은경 님에게 맡겨 줘. 교육 파견이야.",
    # #526 K-EXAONE 회귀 사고(내 결재 진행 조회가 전사 비서로 가서 외부로 나감)
    "내가 올린 결재 진행 상황 보여 줘.",
]
NOT_HR = [
    "2027년 3월 9일 화요일 오후 2시부터 3시까지 4명 들어갈 회의실 예약해 줘.",
    "출장비 규정이 어떻게 돼?",
    "내 회의실 예약 목록 보여 줘.",
]
SYSTEM = "당신은 사내 AI 비서입니다. 휴가·병가·대결 요청은 인사 에이전트로 안내합니다."
HR_TOOL = {"type": "function", "function": {"name": "leave_request", "description": "휴가·반차 결재를 올립니다.",
                                            "parameters": {"type": "object", "properties": {}}}}


def _body(text, system=SYSTEM, tools=(HR_TOOL,)):
    return {"model": "external", "tools": list(tools),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]}


@pytest.fixture(scope="module")
def pack_glossary():
    return Glossary.load(PACK)


@pytest.mark.parametrize("text", INCIDENTS)
def test_pack_topic_catches_incident_sentences(pack_glossary, text):
    v = pack_glossary.check(_body(text))
    assert v is not None and v.action == "local_only" and v.topics == ("hr-attendance",)


@pytest.mark.parametrize("text", NOT_HR)
def test_non_hr_requests_are_not_caught_even_with_hr_words_in_system_and_tools(pack_glossary, text):
    assert pack_glossary.check(_body(text)) is None


def test_topics_look_at_tool_call_arguments_and_tool_results_and_text_parts(pack_glossary):
    calls = {"model": "external", "messages": [
        {"role": "user", "content": "이거 처리해 줘"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "x", "arguments": json.dumps({"kind": "병가"},
                                                                                             ensure_ascii=False)}}]}]}
    assert pack_glossary.check(calls).topics == ("hr-attendance",)
    result = {"model": "external", "messages": [{"role": "user", "content": "남은 거 알려 줘"},
                                                 {"role": "tool", "tool_call_id": "c1", "content": "연차 잔여 7일"}]}
    assert pack_glossary.check(result).topics == ("hr-attendance",)
    parts = {"model": "external", "messages": [{"role": "user", "content": [{"type": "text", "text": "반차 쓸게"}]}]}
    assert pack_glossary.check(parts).topics == ("hr-attendance",)


def test_block_topic_and_terms_combine():
    g = Glossary.from_doc({"terms": [{"term": "오리온", "level": "confidential", "action": "local_only"}],
                           "topics": [{"id": "pay", "action": "block", "reason": "급여는 막습니다",
                                       "patterns": ["급여"]}]})
    v = g.check(_body("오리온 담당 급여 알려 줘"))
    assert v.action == "block" and v.hits == 1 and v.topics == ("pay",) and v.reason == "급여는 막습니다"
    v = g.check(_body("오리온 일정"))
    assert v.action == "local_only" and v.topics == ()


def test_topic_patterns_ignore_case():
    g = Glossary.from_doc({"terms": [], "topics": [{"id": "pto", "action": "local_only", "patterns": ["pto"]}]})
    assert g.check(_body("PTO request")).topics == ("pto",)


def test_bad_topic_action_fails_fast():
    with pytest.raises(ValueError):
        Glossary.from_doc({"terms": [], "topics": [{"id": "x", "action": "allow", "patterns": ["a"]}]})


@pytest.mark.parametrize("text", INCIDENTS[:2])
def test_external_allowed_agent_hr_request_goes_local(client, app, token_for, litellm, text):
    _, external_ok = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": [{"role": "user", "content": text}]})
    assert r.status_code == 200
    assert r.headers["x-egress-location"] == "local" and litellm.last_body()["model"] == "local"
    assert app.state.audit.egress.read_all() == []
    redacted = [e for e in _audit(app) if e["kind"] == "llm.redacted"][-1]
    assert "hr-attendance" in redacted["detail"] and "로컬" in redacted["detail"]
    assert text[:8] not in json.dumps(_audit(app), ensure_ascii=False)  # 문장은 남기지 않음


def test_external_allowed_agent_non_hr_request_still_goes_external(client, app, token_for, litellm):
    _, external_ok = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": [{"role": "user", "content": NOT_HR[1]}]})
    assert r.status_code == 200 and r.headers["x-egress-location"] == "external"


@pytest.mark.parametrize("message", [
    # ensure_ascii=True로 만든 도구 인자(\uXXXX만 남음)
    {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "x", "arguments": json.dumps({"kind": "병가"})}}]},
    # 도구 결과도 이스케이프된 JSON일 수 있음
    {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"leave": "연차 7일"})},
    # 레거시 function_call
    {"role": "assistant", "content": None, "function_call": {"name": "x", "arguments": "{\"kind\": \"반차\"}"}},
    # tool content 리스트
    {"role": "tool", "tool_call_id": "c1", "content": [{"type": "text", "text": "휴가 잔여"}]},
    # 자모로 나뉜 NFD 한글
    {"role": "user", "content": __import__("unicodedata").normalize("NFD", "내일 병가 신청해 줘")},
])
def test_topics_survive_escaped_legacy_and_nfd_shapes(pack_glossary, message):
    body = {"model": "external", "messages": [{"role": "user", "content": "그거 처리해 줘"}, message]}
    v = pack_glossary.check(body)
    assert v is not None and v.topics == ("hr-attendance",)


def test_earlier_turn_keeps_conversation_local(pack_glossary):
    body = {"model": "external", "messages": [
        {"role": "user", "content": "다음 주 금요일 연차 쓸게"}, {"role": "assistant", "content": "날짜를 확인할게요"},
        {"role": "user", "content": "응 그렇게 해 줘"}]}
    assert pack_glossary.check(body).topics == ("hr-attendance",)


def test_stream_hr_request_goes_local(client, app, token_for, litellm):
    _, external_ok = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "stream": True, "messages": [{"role": "user", "content": INCIDENTS[0]}]})
    assert r.status_code == 200 and litellm.last_body()["model"] == "local"


def test_block_topic_is_403_without_sentence_in_audit(client, app, token_for, litellm):
    app.state.egress.glossary = Glossary.from_doc({"terms": [], "topics": [
        {"id": "pay", "action": "block", "reason": "급여는 외부로 보내지 않습니다", "patterns": ["급여"]}]})
    _, external_ok = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": [{"role": "user", "content": "김철수 급여 명세 요약"}]})
    assert r.status_code == 403 and r.json()["type"] == "urn:problem:confidential" and litellm.requests == []
    ev = _audit(app)[-1]
    assert ev["detail"] == "업무 주제 pay: 차단" and "김철수" not in json.dumps(_audit(app), ensure_ascii=False)
