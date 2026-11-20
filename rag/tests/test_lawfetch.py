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


def test_조문_상자_안쪽_div의_버튼_글자는_본문에_넣지_않는다(law):
    for section in law["sections"]:
        assert "위임행정규칙" not in section["text"]


def test_안쪽_div_뒤에_이어지는_항도_남긴다():
    page = (FIXTURES / "law_sample.html").read_text(encoding="utf-8")
    head = page[: page.find('<div class="lawcon">')]
    block = (
        '<div class="lawcon"><p><label for="Y1">제9조(시험)</label> ① 첫 항 </p>'
        '<div class="rule_area"><div class="btn_rule"><img alt="위임행정규칙" /></div></div>'
        "<p>② 둘째 항</p></div>"
    )
    parsed = parse_law_html(head + block)
    assert parsed["sections"][0]["text"] == "① 첫 항\n② 둘째 항"


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


def test_쪽_번호를_못_읽은_쪽도_장_안에_있으면_고른다():
    pages = PAGES[:4] + ["표만 있는 쪽"] + PAGES[4:]
    _, picked = chapter_pages(pages, 8)
    assert picked == pages[3:6]


def test_목차에_장이_없으면_실패한다():
    with pytest.raises(ValueError):
        chapter_pages(PAGES, 12)


# ---------------------------------------------------------------- 옛 판 받기


def _serve(monkeypatch, seen):
    import rag.lawfetch as lf

    page = (FIXTURES / "law_sample.html").read_bytes()

    def fake_get(url):
        seen.append(url)
        return page

    monkeypatch.setattr(lf, "_get", fake_get)


def test_옛_판은_연혁의_일련번호와_시행일로_받고_주소에_시행일을_남긴다(monkeypatch):
    from rag.lawfetch import fetch_law_edition

    seen = []
    _serve(monkeypatch, seen)
    got = fetch_law_edition("d", {"name": "국가공무원 복무규정"}, {"lsiSeq": "123", "efYd": "20261002"})
    assert "lsiSeq=123" in seen[0] and "efYd=20261002" in seen[0]
    assert got["effectiveDate"] == "2026-10-02"
    assert got["url"].endswith("lsiSeq=123&efYd=20261002")


def test_받은_판의_시행일이_요청과_다르면_실패한다(monkeypatch):
    from rag.lawfetch import fetch_law_edition

    _serve(monkeypatch, [])
    with pytest.raises(ValueError, match="시행일"):
        fetch_law_edition("d", {"name": "국가공무원 복무규정"}, {"lsiSeq": "123", "efYd": "20260101"})


def test_옛_판의_법령_이름이_다르면_실패한다(monkeypatch):
    from rag.lawfetch import fetch_law_edition

    _serve(monkeypatch, [])
    with pytest.raises(ValueError, match="이름"):
        fetch_law_edition("d", {"name": "공무원 여비 규정"}, {"lsiSeq": "123", "efYd": "20261002"})


# ---------------------------------------------------------------- 별표(HWP)

APPENDIX_HTML = (
    '<a class="blu" onclick="bylInfoDiv(\'1\');" href="#AJAX"> [별표 2] 국내 여비 지급표(제10조 관련) </a> '
    '<a href="flDownload.do?gubun=&amp;flSeq=169708641&amp;bylClsCd=110201"> '
    '<img alt="HWP파일 다운로드" src="x.svg" /> </a> '
    '<a href="flDownload.do?gubun=&amp;flSeq=169708643&amp;bylClsCd=110201"> <img alt="PDF파일 다운로드" /> </a>'
)


def test_본문에서_별표의_HWP_파일_번호를_고른다():
    from rag.lawfetch import appendix_links

    assert appendix_links(APPENDIX_HTML) == {"2": ("국내 여비 지급표(제10조 관련)", "169708641")}


def test_별표를_받아_표를_절로_넣고_파일_해시를_남긴다(monkeypatch):
    import hashlib

    import rag.lawfetch as lf

    blob = (FIXTURES / "travel_appendix2.hwp").read_bytes()
    seen = []
    monkeypatch.setattr(lf, "_get", lambda url: seen.append(url) or blob)
    sections, hashes = lf.fetch_appendices("d", APPENDIX_HTML, [2])
    assert seen == [f"{lf.BASE}/flDownload.do?flSeq=169708641"]
    [s] = sections
    assert s["label"] == "별표 2" and s["heading"] == "국내 여비 지급표(제10조 관련)"
    assert "일비 (1일당): 25,000" in s["text"]
    assert hashes == {"별표 2": hashlib.sha256(blob).hexdigest()}


def test_없는_별표를_요청하면_실패한다():
    from rag.lawfetch import fetch_appendices

    with pytest.raises(ValueError, match="별표 3"):
        fetch_appendices("d", APPENDIX_HTML, [3])
