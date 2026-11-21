"""IT 서비스 팩 생성 문서(#459): 본문이 팩 값으로 채워지고 태그 범위 안에서만 찾히는지 봅니다."""

import pytest

from rag.app import build_index
from rag.embed import HashEmbedder
from rag.generate import render_document
from rag.pack import load_pack

TAGS = {
    "its-work-rules": "public",
    "its-leave-rules": "hr-policy",
    "its-project-standards": "project-standards",
    "its-ops-runbook": "ops-runbook",
    "its-customer-contract-sample": "customer-contracts",
}
QUESTIONS = [
    ("공수 보고는 언제까지 올려야 해?", "project-standards", "its-project-standards", "제2조(공수 보고)"),
    ("범위가 바뀌는 고객사 요청은 어떻게 받아?", "project-standards", "its-project-standards", "제4조(변경 관리)"),
    ("1등급 장애는 몇 분 안에 대응을 시작해?", "ops-runbook", "its-ops-runbook", "제3조(장애 등급과 보고 시간)"),
    ("관리자 권한 계정은 누가 승인해야 발급해?", "ops-runbook", "its-ops-runbook", "제5조(계정 발급)"),
    ("가용률이 목표에 못 미치면 위약금은 얼마야?", "customer-contracts", "its-customer-contract-sample", "제3조(위약금)"),
    ("프로젝트 투입 중에 연속 휴가는 언제까지 신청해?", "hr-policy", "its-leave-rules", "제4조(프로젝트 투입 중 휴가)"),
]


@pytest.fixture(scope="module")
def itpack():
    mp = pytest.MonkeyPatch()
    mp.setenv("RAG_PACK", "it-services")
    mp.delenv("PACK_DIR", raising=False)
    yield load_pack(), build_index(HashEmbedder())
    mp.undo()


def test_문서_템플릿을_팩_값으로_채운다(itpack):
    pack, _ = itpack
    assert [d["id"] for d in pack.documents] == list(TAGS)
    for doc_id in TAGS:
        text = "".join(s["text"] for s in render_document(doc_id, pack))
        assert "{{" not in text


def test_장애_등급_담당은_팩의_역할_이름을_쓴다(itpack):
    pack, _ = itpack
    sections = {s["label"]: s["text"] for s in render_document("its-ops-runbook", pack)}
    assert "적용 대상은 운영 티켓 담당입니다" in sections["제1조"]
    assert "사업부장에게 알립니다" in sections["제3조"]


@pytest.mark.parametrize("question,tag,doc_id,article", QUESTIONS)
def test_질문에_맞는_조문이_해당_태그_범위에서_상위에_나온다(itpack, question, tag, doc_id, article):
    _, index = itpack
    top = index.search(question, {"public", tag}, "hybrid", top_k=3)
    assert (doc_id, article) in [(h.chunk.doc_id, h.chunk.article) for h in top]


@pytest.mark.parametrize("doc_id", list(TAGS))
def test_문서는_자기_태그가_없으면_찾지_않는다(itpack, doc_id):
    _, index = itpack
    others = set(TAGS.values()) - {TAGS[doc_id]}
    for q, *_ in QUESTIONS:
        assert all(h.chunk.doc_id != doc_id for h in index.search(q, others, "hybrid", top_k=50))
