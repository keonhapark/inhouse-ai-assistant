"""금융 팩 생성 문서(#408): 본문이 팩 값으로 채워지고 태그 범위 안에서만 찾히는지 봅니다."""

import pytest

from rag.app import build_index
from rag.embed import HashEmbedder
from rag.generate import render_document
from rag.pack import load_pack

DOCS = ["fin-work-rules", "fin-leave-rules", "fin-credit-rules", "fin-ethics-code", "fin-control-findings"]
TAGS = {
    "fin-work-rules": "public",
    "fin-leave-rules": "hr-policy",
    "fin-credit-rules": "credit-policy",
    "fin-ethics-code": "internal-rules",
    "fin-control-findings": "compliance-restricted",
}
QUESTIONS = [
    ("여신 금액 5억이면 누가 전결해?", "credit-policy", "fin-credit-rules", "제3조(전결 한도)"),
    ("아파트 담보 인정 비율은 얼마야?", "credit-policy", "fin-credit-rules", "제5조(담보 인정 비율)"),
    ("고객 목록을 개인 메신저로 보내도 돼?", "internal-rules", "fin-ethics-code", "제4조(자료 반출)"),
    ("가족이 차주인 업무는 어떻게 해야 해?", "internal-rules", "fin-ethics-code", "제2조(이해상충의 신고)"),
    ("연속 휴가는 연 몇 번 써야 해?", "hr-policy", "fin-leave-rules", "제7조(연속 휴가 의무)"),
]


@pytest.fixture(scope="module")
def finance(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("RAG_PACK", "finance")
    mp.delenv("PACK_DIR", raising=False)
    yield load_pack(), build_index(HashEmbedder())
    mp.undo()


def test_문서_템플릿을_팩_값으로_채운다(finance):
    pack, _ = finance
    assert [d["id"] for d in pack.documents] == DOCS
    for doc_id in DOCS:
        text = "".join(s["text"] for s in render_document(doc_id, pack))
        assert "{{" not in text
        if doc_id != "fin-control-findings":
            assert "가상누리은행" in text


def test_전결_한도는_여신_품의_양식을_따른다(finance):
    pack, _ = finance
    text = {s["label"]: s["text"] for s in render_document("fin-credit-rules", pack)}["제3조"]
    assert "100,000,000원 이하" in text and "부점장" in text and "은행장" in text


@pytest.mark.parametrize("question,tag,doc_id,article", QUESTIONS)
def test_질문에_맞는_조문이_해당_태그_범위에서_상위에_나온다(finance, question, tag, doc_id, article):
    _, index = finance
    top = index.search(question, {"public", tag}, "hybrid", top_k=3)
    assert (doc_id, article) in [(h.chunk.doc_id, h.chunk.article) for h in top]


@pytest.mark.parametrize("doc_id", DOCS)
def test_문서는_자기_태그가_없으면_찾지_않는다(finance, doc_id):
    _, index = finance
    others = set(TAGS.values()) - {TAGS[doc_id]}
    for q, *_ in QUESTIONS:
        assert all(h.chunk.doc_id != doc_id for h in index.search(q, others, "hybrid", top_k=50))
