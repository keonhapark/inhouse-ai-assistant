from rag.chunk import chunk_documents, split_section
from rag.corpus import Document, Section


def test_짧은_조문은_한_청크다():
    s = Section("제1조", "목적", "이 영은 목적을 정한다.")
    assert split_section(s, 100) == [("제1조(목적)", "이 영은 목적을 정한다.")]


def test_긴_조문은_항_경계에서_나누고_항_범위를_붙인다():
    text = "\n".join(["① " + "가" * 30, "② " + "나" * 30, "③ " + "다" * 30])
    parts = split_section(Section("제5조", "휴가", text), 70)
    assert [a for a, _ in parts] == ["제5조(휴가) 제1항~제2항", "제5조(휴가) 제3항"]
    assert "\n".join(b for _, b in parts) == text


def test_예규_항목_표시도_경계로_쓴다():
    text = "(1) " + "가" * 40 + "\n(2) " + "나" * 40
    parts = split_section(Section("4. 가.", "연가", text), 50)
    assert [a for a, _ in parts] == ["4. 가.(연가) (1)", "4. 가.(연가) (2)"]


def test_경계로도_긴_덩어리는_줄과_글자로_자르고_원문을_잃지_않는다():
    text = "① " + "가" * 120 + "\n둘째 줄"
    parts = split_section(Section("제7조", None, text), 50)
    assert all(len(b) <= 50 for _, b in parts)
    assert all(a == "제7조 제1항" for a, _ in parts)
    assert "".join(b.replace("\n", "") for _, b in parts) == text.replace("\n", "")


def test_청크는_문서의_ACL과_신뢰_등급을_물려받는다():
    doc = Document("d1", "문서", "guide", ("hr-policy",), "untrusted", 1, {}, (Section("제1조", None, "본문"),))
    [c] = chunk_documents([doc])
    assert (c.id, c.doc_id, c.acl_tags, c.trust) == ("d1#1", "d1", frozenset({"hr-policy"}), "untrusted")


def test_항목이_있는_절은_항목만_경계로_쓰고_번호가_거꾸로_가면_경계로_보지_않는다():
    text = "\n".join(["(1) " + "가" * 20, "① 표 기호", "(2) " + "나" * 20, "(1) 인용 번호", "(3) " + "다" * 20])
    parts = split_section(Section("4. 라.", "특별휴가", text), 40)
    assert [a for a, _ in parts] == ["4. 라.(특별휴가) (1)", "4. 라.(특별휴가) (2)", "4. 라.(특별휴가) (3)"]
    assert "① 표 기호" in parts[0][1] and "(1) 인용 번호" in parts[1][1]
