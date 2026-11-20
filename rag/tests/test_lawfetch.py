"""법제처 본문 파서 시험. 네트워크는 쓰지 않고 저장한 응답 일부와 만든 쪽 글로 봅니다."""

from pathlib import Path

import pytest

from rag.lawfetch import chapter_pages, parse_admrul_chapter, parse_law_html

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def law():
    return parse_law_html((FIXTURES / "law_sample.html").read_text(encoding="utf-8"))


def test_법령_머리에서_제목_시행일_공포정보를_읽는다(law):
    assert law["title"] == "국가공무원 복무규정"
    assert law["effectiveDate"] == "2026-10-02"
    assert law["promulgation"].startswith("대통령령 제36728호")


def test_조문을_label과_heading으로_나누고_삭제된_조문은_뺀다(law):
    labels = [(s["label"], s["heading"]) for s in law["sections"]]
    assert labels == [("제1조", "목적"), ("제15조", "연가 일수")]


def test_개정_표시를_지우고_링크_사이에_공백을_끼우지_않는다(law):
    first = law["sections"][0]["text"]
    assert "제55조부터 제59조까지" in first
    assert "개정" not in law["sections"][1]["text"]


def test_그림으로_든_표는_대체_글자를_행마다_남긴다(law):
    text = law["sections"][1]["text"]
    assert "\n1개월 이상 1년 미만 11\n" in text
    assert "\n6년 이상 21\n" in text


def test_머리가_없으면_실패한다():
    with pytest.raises(ValueError):
        parse_law_html("<html></html>")


TOC = " 제 7장  공무국외출장 등············ 125\n 제 8장  휴 가······················145\n 제 9장  영리업무 금지·············209\n"
PAGES = [
    "표지",
    "차    례\n" + TOC,
    "124\n제7장 / 공무국외출장 등\n앞 장 내용",
    "145\n제  장\n휴  가\n1. 근 거\n 가. 복무규정 제14조 내지 제24조\n2. 휴가의 개념\n 가. 정  의\n○ 출근 의무를 면제하는 것",
    "146\n규정 이름\n 나. 휴가의 종류\n (1) 연가\n 1. 「병역법」에 따른 검사\n  가. 목록 속 가목은 머리가 아님\n"
    "3. 시간선택제 특례\n 가. 「공무원임용령」 제3조의2제3호에 따른 시간선택제임기제공무원, 같은 조 제4호\n이어지는 문장\n"
    "1. 인용한 규정의 번호는 머리가 아님",
    "209\n제9장 / 영리업무 금지\n다음 장 내용",
]


def test_목차로_장의_쪽만_고른다():
    name, picked = chapter_pages(PAGES, 8)
    assert name == "휴가"
    assert [p.split("\n", 1)[0] for p in picked] == ["145", "146"]


def test_예규_장을_번호_순서대로_두_단계_절로_나눈다():
    _, sections = parse_admrul_chapter(PAGES, 8, "규정 이름")
    got = [(s["label"], s["heading"]) for s in sections]
    assert got == [
        ("1. 가.", "근거"),
        ("2. 가.", "휴가의 개념 > 정의"),
        ("2. 나.", "휴가의 개념 > 휴가의 종류"),
        ("3. 가.", "시간선택제 특례"),
    ]
    # 머리만 있는 절은 머리 내용이 본문이 됩니다.
    assert sections[0]["text"] == "복무규정 제14조 내지 제24조"
    # 순서가 맞지 않는 번호와 목록 속 가목은 본문에 남습니다.
    assert "목록 속 가목은 머리가 아님" in sections[2]["text"]
    assert "1. 인용한 규정의 번호는 머리가 아님" in sections[3]["text"]
    # 긴 "가." 줄은 머리가 아니라 문장이므로 본문 첫 줄로 둡니다.
    assert sections[3]["text"].startswith("가. 「공무원임용령」")
    # 쪽 번호, 장 머리, 규정 이름 줄은 지웁니다.
    joined = "\n".join(s["text"] for s in sections)
    for noise in ["145", "규정 이름", "휴  가"]:
        assert noise not in joined.splitlines()


def test_목차에_장이_없으면_실패한다():
    with pytest.raises(ValueError):
        chapter_pages(PAGES, 12)
