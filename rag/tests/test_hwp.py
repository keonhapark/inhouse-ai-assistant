"""HWP 5.0 표 파서 시험.

`fixtures/travel_appendix2.hwp`는 국가법령정보센터에서 받은 「공무원 여비 규정」 별표 2(2026. 6. 30. 개정)입니다.
법령의 별표라 저작권법 제7조로 보호받지 않습니다. 나머지는 레코드를 직접 만들어 봅니다.
"""

import struct
from pathlib import Path

import pytest

from rag.hwp import (
    CTRL_HEADER, LIST_HEADER, PARA_HEADER, PARA_TEXT, TABLE, Cell, HwpError, Table, blocks_text, build_tree,
    para_text, read_hwp, read_records, table_lines,
)

FIXTURE = Path(__file__).parent / "fixtures" / "travel_appendix2.hwp"


def rec(tag: int, level: int, data: bytes) -> bytes:
    if len(data) >= 0xFFF:
        return struct.pack("<II", tag | (level << 10) | (0xFFF << 20), len(data)) + data
    return struct.pack("<I", tag | (level << 10) | (len(data) << 20)) + data


def utf16(text: str) -> bytes:
    return text.encode("utf-16le")


def cell(level: int, row: int, col: int, rowspan: int = 1, colspan: int = 1) -> bytes:
    return rec(LIST_HEADER, level, struct.pack("<HHIHHHH", 1, 0, 0, col, row, colspan, rowspan) + b"\0" * 16)


def table_records(cells: list[tuple[int, int, int, int, str]], rows: int, cols: int) -> bytes:
    out = rec(PARA_HEADER, 0, b"\0" * 22) + rec(CTRL_HEADER, 1, b" lbt" + b"\0" * 4)
    out += rec(TABLE, 2, struct.pack("<IHH", 0, rows, cols))
    for row, col, rowspan, colspan, text in cells:
        out += cell(2, row, col, rowspan, colspan)
        for para in text.split("\n"):
            out += rec(PARA_HEADER, 2, b"\0" * 22) + rec(PARA_TEXT, 3, utf16(para + "\r"))
    return out


def test_긴_레코드는_크기를_따로_읽는다():
    data = rec(PARA_TEXT, 0, utf16("가" * 3000))
    [r] = read_records(data)
    assert len(r.data) == 6000


def test_레코드_길이가_본문보다_길면_실패한다():
    with pytest.raises(HwpError):
        read_records(struct.pack("<I", PARA_TEXT | (100 << 20)) + b"\0" * 10)


def test_인라인_확장_제어는_8글자를_건너뛰고_줄바꿈과_탭을_남긴다():
    inline = struct.pack("<8H", 9, 0, 0, 0, 0, 0, 0, 9)
    extended = struct.pack("<8H", 11, *b" lbt", 0, 0, 11)
    data = utf16("가") + inline + utf16("나") + extended + utf16("다") + struct.pack("<H", 10) + utf16("라\r")
    assert para_text(data) == "가 나다\n라"


def test_레벨로_부모_자식을_잇는다():
    roots = build_tree(read_records(rec(PARA_HEADER, 0, b"") + rec(PARA_TEXT, 1, b"") + rec(PARA_HEADER, 0, b"")))
    assert [len(r.children) for r in roots] == [1, 0]


def test_병합_셀은_차지한_칸마다_글을_채운다():
    t = Table(2, 3, [Cell(0, 0, 2, 1, ["구분"]), Cell(0, 1, 1, 2, ["운임"]), Cell(1, 1, 1, 1, ["철도"]),
                     Cell(1, 2, 1, 1, ["선박"])])
    assert t.grid() == [["구분", "운임", "운임"], ["구분", "철도", "선박"]]


def test_표를_머리_값_줄로_옮기고_전체_폭_행은_문단마다_줄로_둔다():
    t = Table(4, 2, [
        Cell(0, 0, 1, 2, ["제목"]),
        Cell(1, 0, 1, 1, ["구분"]), Cell(1, 1, 1, 1, ["일비", "(1일당)"]),
        Cell(2, 0, 1, 1, ["제1호"]), Cell(2, 1, 1, 1, ["25,000"]),
        Cell(3, 0, 1, 2, ["비고: 1. 첫째", "2. 둘째"]),
    ])
    assert table_lines(t) == ["제목", "구분: 제1호 / 일비 (1일당): 25,000", "비고: 1. 첫째", "2. 둘째"]


def test_가로로_병합한_머리와_값은_한_번만_적는다():
    t = Table(2, 3, [Cell(0, 0, 1, 1, ["구분"]), Cell(0, 1, 1, 2, ["운임"]),
                     Cell(1, 0, 1, 1, ["제1호"]), Cell(1, 1, 1, 2, ["실비"])])
    assert table_lines(t) == ["구분: 제1호 / 운임: 실비"]


def test_레코드에서_표를_읽는다():
    from rag.hwp import _paragraph_blocks

    data = table_records([(0, 0, 1, 1, "구분"), (0, 1, 1, 1, "숙박비\n(1박당)"),
                          (1, 0, 1, 1, "제2호"), (1, 1, 1, 1, "실비")], 2, 2)
    [para] = build_tree(read_records(data))
    [table] = _paragraph_blocks(para)
    assert table_lines(table) == ["구분: 제2호 / 숙박비 (1박당): 실비"]


def test_HWP_파일이_아니면_실패한다():
    with pytest.raises(HwpError):
        read_hwp(b"%PDF-1.4 not hwp")


def test_실제_별표_파일에서_표와_비고를_읽는다():
    text = blocks_text(read_hwp(FIXTURE.read_bytes()))
    lines = text.split("\n")
    assert lines[1] == "국내 여비 지급표(제10조부터 제13조까지 및 제16조제1항 관련)"
    assert ("구분: 제2호 / 철도운임: 실비 (일반실) / 선박운임: 실비 (2등급) / 항공운임: 실비 / 자동차 운임: 실비 / "
            "일비 (1일당): 25,000 / 숙박비 (1박당): 실비 (상한액: 서울특별시 100,000, 광역시 80,000, "
            "그 밖의 지역은 70,000) / 식비 (1일당): 25,000") in lines
    assert lines[-1] == "6. 운임 및 숙박비의 할인이 가능한 경우에는 할인된 요금을 지급한다."
    assert sum(x[:2] in ("비고", "1.", "1의", "2.", "3.", "4.", "5.", "6.") for x in lines) == 7


def test_표_머리의_행렬이_너무_크면_실패한다():
    data = rec(PARA_HEADER, 0, b"") + rec(CTRL_HEADER, 1, b" lbt") + rec(TABLE, 2, struct.pack("<IHH", 0, 60000, 60000))
    from rag.hwp import _paragraph_blocks

    [para] = build_tree(read_records(data))
    with pytest.raises(HwpError, match="너무 큽니다"):
        _paragraph_blocks(para)


def test_압축을_푼_본문이_상한을_넘으면_실패한다(monkeypatch):
    import zlib

    import rag.hwp as hwp

    monkeypatch.setattr(hwp, "MAX_SECTION_BYTES", 1000)
    c = zlib.compressobj(wbits=-15)
    raw = c.compress(b"\0" * 5000) + c.flush()
    with pytest.raises(HwpError, match="상한"):
        hwp._inflate(raw)
