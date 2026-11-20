import pytest

from gateway.confidential import Glossary

DOC = {"terms": [
    {"term": "프로젝트 해오름", "aliases": ["HAEOREUM"], "level": "confidential", "action": "local_only"},
    {"term": "원가표", "level": "confidential", "action": "block", "reason": "원가 정보는 외부로 보내지 않습니다"},
]}


def _body(text):
    return {"model": "external", "messages": [{"role": "user", "content": text}]}


def test_no_terms_no_verdict(tmp_path):
    assert Glossary.load(tmp_path).check(_body("아무거나")) is None


def test_alias_and_case_insensitive():
    v = Glossary.from_doc(DOC).check(_body("haeoreum 일정 알려 줘"))
    assert v.action == "local_only" and v.hits == 1


def test_block_wins():
    v = Glossary.from_doc(DOC).check(_body("프로젝트 해오름 원가표 요약"))
    assert v.action == "block" and v.hits == 2 and "원가" in v.reason


def test_looks_into_text_parts_and_tool_calls():
    g = Glossary.from_doc(DOC)
    assert g.check({"messages": [{"role": "user", "content": [{"type": "text", "text": "원가표"}]}]})
    assert g.check({"messages": [{"role": "assistant", "content": None,
                                  "tool_calls": [{"function": {"arguments": "{\"q\": \"원가표\"}"}}]}]})


def test_bad_action_fails_fast():
    with pytest.raises(ValueError):
        Glossary.from_doc({"terms": [{"term": "x", "action": "allow"}]})
