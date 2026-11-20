"""팩 문서 목록의 본문이 모두 있고, 출처·ACL·신뢰 등급이 docs.yaml과 맞는지 봅니다."""

import re

import pytest

from rag.corpus import MissingBody, load_documents
from rag.pack import load_pack

PHONE = re.compile(r"\b0\d{1,2}-\d{3,4}-\d{4}\b")


@pytest.fixture(scope="module")
def pack():
    return load_pack()


@pytest.fixture(scope="module")
def docs(pack):
    return {d.id: d for d in load_documents(pack, stage=1)}


def test_1단계_문서는_모두_본문이_있다(pack, docs):
    expected = {d["id"] for d in pack.documents if d["stage"] <= 1}
    assert set(docs) == expected
    for doc in docs.values():
        assert doc.sections, doc.id
        assert all(s.text.strip() for s in doc.sections), doc.id


def test_ACL_태그와_신뢰_등급은_docs_yaml을_따른다(pack, docs):
    for entry in pack.documents:
        doc = docs[entry["id"]]
        assert doc.acl_tags == tuple(entry["acl_tags"])
        assert doc.trust == entry["trust"]


def test_공개_규정_고정본에는_출처_주소_조회일_시행일_원문_해시가_있다(docs):
    laws = [d for d in docs.values() if d.source["type"] == "law_open_api"]
    assert len(laws) == 3
    for doc in laws:
        src = doc.source
        assert src["url"].startswith("https://www.law.go.kr/LSW/")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", src["effectiveDate"])
        assert src["retrievedAt"]
        assert re.fullmatch(r"[0-9a-f]{64}", src["rawSha256"])
        assert "저작권법 제7조" in src["license"]


def test_법령_조문_표시는_제N조_꼴이다(docs):
    doc = docs["law-civil-service-duty"]
    assert all(re.fullmatch(r"제\d+조(의\d+)?", s.label) for s in doc.sections)
    by_label = {s.label: s for s in doc.sections}
    assert by_label["제15조"].article == "제15조(연가 일수)"


def test_생성_문서에는_채우지_않은_자리표시자가_없다(docs):
    for doc in docs.values():
        if doc.source["type"] == "generated":
            for s in doc.sections:
                assert "{{" not in s.text and "}}" not in s.text, (doc.id, s.label)


def test_제한_문서는_제한_태그만_가진다(pack, docs):
    restricted = [e["id"] for e in pack.documents if e["title"].endswith("(제한)")]
    assert restricted
    for doc_id in restricted:
        assert "public" not in docs[doc_id].acl_tags


def test_본문에_전화번호가_없다(docs):
    for doc in docs.values():
        for s in doc.sections:
            assert not PHONE.search(s.text), (doc.id, s.label)


def test_고정본이_없으면_알린다(pack, tmp_path):
    with pytest.raises(MissingBody):
        load_documents(pack, law_dir=tmp_path)
