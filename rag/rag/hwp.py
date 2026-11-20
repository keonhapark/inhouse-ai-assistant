"""HWP 5.0 문서에서 문단과 표를 뽑습니다(법령 별표용).

국가법령정보센터는 별표를 HWP 5.0(바이너리)과 PDF로만 줍니다. PDF는 표 모양이 남지 않아 행·열을 다시 맞출 수
없으므로 HWP의 표 레코드에서 셀 주소와 병합을 읽습니다. 형식은 한글과컴퓨터가 공개한 "한글 문서 파일 형식 5.0"을
따랐고, OLE 컨테이너는 olefile(BSD-2-Clause)로 엽니다. 받을 때만 씁니다(의존 그룹 fetch).

다루는 것: 압축된 본문(BodyText/Section*), 문단 글(PARA_TEXT), 표(CTRL_HEADER 'tbl ', TABLE, 셀 LIST_HEADER),
셀 안의 표(셀 글에 행을 " / "로 이어 넣음). 다루지 않는 것: 암호·배포용 문서, 그림, 글상자, 각주.
"""

from __future__ import annotations

import io
import struct
import zlib
from dataclasses import dataclass, field

TAG_BEGIN = 0x10
PARA_HEADER = TAG_BEGIN + 50
PARA_TEXT = TAG_BEGIN + 51
CTRL_HEADER = TAG_BEGIN + 55
LIST_HEADER = TAG_BEGIN + 56
TABLE = TAG_BEGIN + 61
TABLE_CTRL = b"tbl "

# 글자 하나(2바이트)만 차지하는 제어 문자. 나머지 0~31은 확장·인라인 제어로 8글자(16바이트)를 차지합니다.
_CHAR_CONTROLS = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}


class HwpError(Exception):
    pass


@dataclass
class Record:
    tag: int
    level: int
    data: bytes
    children: list[Record] = field(default_factory=list)


@dataclass
class Cell:
    row: int
    col: int
    rowspan: int
    colspan: int
    text: str


@dataclass
class Table:
    rows: int
    cols: int
    cells: list[Cell]

    def grid(self) -> list[list[str]]:
        """병합한 셀의 글을 차지한 모든 칸에 채운 행렬."""
        out = [["" for _ in range(self.cols)] for _ in range(self.rows)]
        for c in self.cells:
            for r in range(c.row, min(c.row + c.rowspan, self.rows)):
                for k in range(c.col, min(c.col + c.colspan, self.cols)):
                    out[r][k] = c.text
        return out


Block = str | Table


def read_records(data: bytes) -> list[Record]:
    out = []
    pos = 0
    while pos + 4 <= len(data):
        (head,) = struct.unpack_from("<I", data, pos)
        pos += 4
        tag, level, size = head & 0x3FF, (head >> 10) & 0x3FF, head >> 20
        if size == 0xFFF:
            (size,) = struct.unpack_from("<I", data, pos)
            pos += 4
        if pos + size > len(data):
            raise HwpError("레코드 길이가 본문보다 깁니다")
        out.append(Record(tag, level, data[pos : pos + size]))
        pos += size
    return out


def build_tree(records: list[Record]) -> list[Record]:
    """레벨로 부모·자식을 잇습니다. 뒤따르는 레코드 중 레벨이 더 큰 것이 자식입니다."""
    roots: list[Record] = []
    stack: list[Record] = []
    for r in records:
        while stack and stack[-1].level >= r.level:
            stack.pop()
        (stack[-1].children if stack else roots).append(r)
        stack.append(r)
    return roots


def para_text(data: bytes) -> str:
    chars = []
    units = struct.unpack(f"<{len(data) // 2}H", data[: len(data) // 2 * 2])
    i = 0
    while i < len(units):
        u = units[i]
        if u >= 32:
            chars.append(chr(u))
            i += 1
        elif u in _CHAR_CONTROLS:
            if u == 10:
                chars.append("\n")
            i += 1
        else:
            if u == 9:
                chars.append(" ")  # 탭(인라인 제어)
            i += 8
    return "".join(chars).strip()


def _paragraph_blocks(para: Record) -> list[Block]:
    """문단 하나: 글과, 문단에 붙은 표를 순서대로."""
    out: list[Block] = []
    text = "".join(para_text(c.data) for c in para.children if c.tag == PARA_TEXT)
    if text:
        out.append(text)
    for c in para.children:
        if c.tag == CTRL_HEADER and c.data[:4][::-1] == TABLE_CTRL:
            out.append(_table(c))
    return out


def _table(ctrl: Record) -> Table:
    info = next((c for c in ctrl.children if c.tag == TABLE), None)
    if info is None or len(info.data) < 8:
        raise HwpError("표 정보 레코드가 없습니다")
    rows, cols = struct.unpack_from("<HH", info.data, 4)
    cells: list[Cell] = []
    current: Cell | None = None
    parts: list[str] = []
    for c in ctrl.children:
        if c.tag == LIST_HEADER:
            if current is not None:
                current.text = " ".join(parts)
            col, row, colspan, rowspan = struct.unpack_from("<HHHH", c.data, 8)
            current, parts = Cell(row, col, rowspan, colspan, ""), []
            cells.append(current)
        elif c.tag == PARA_HEADER and current is not None:
            for b in _paragraph_blocks(c):
                parts.append(b if isinstance(b, str) else " / ".join(" ".join(x for x in row if x)
                                                                       for row in _dedupe_rows(b.grid())))
    if current is not None:
        current.text = " ".join(parts)
    return Table(rows, cols, cells)


def _dedupe_rows(grid: list[list[str]]) -> list[list[str]]:
    """가로 병합으로 같은 글이 이어 나오면 한 번만 남깁니다."""
    out = []
    for row in grid:
        kept: list[str] = []
        for x in row:
            if not kept or kept[-1] != x:
                kept.append(x)
        out.append(kept)
    return out


def read_hwp(blob: bytes) -> list[Block]:
    import olefile  # 받을 때만 씁니다(의존 그룹 fetch)

    if not olefile.isOleFile(io.BytesIO(blob)):
        raise HwpError("HWP 5.0(OLE) 파일이 아닙니다")
    ole = olefile.OleFileIO(io.BytesIO(blob))
    header = ole.openstream("FileHeader").read()
    if not header.startswith(b"HWP Document File"):
        raise HwpError("HWP 파일 머리가 아닙니다")
    (props,) = struct.unpack_from("<I", header, 36)
    if props & 0b110:  # 암호(bit 1), 배포용(bit 2)
        raise HwpError("암호나 배포용 문서는 읽지 않습니다")
    compressed = bool(props & 1)
    sections = sorted(
        (e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
        key=lambda e: int(e[1][len("Section") :]),
    )
    blocks: list[Block] = []
    for entry in sections:
        raw = ole.openstream("/".join(entry)).read()
        data = zlib.decompress(raw, -15) if compressed else raw
        for root in build_tree(read_records(data)):
            if root.tag == PARA_HEADER:
                blocks.extend(_paragraph_blocks(root))
    return blocks


def table_lines(table: Table) -> list[str]:
    """표를 검색·인용할 글 줄로 옮깁니다.

    - 모든 열을 덮는 행(제목, 단위, 비고)은 그 글을 한 줄로 둡니다.
    - 그 밖의 첫 행을 머리글로 보고, 다음 행마다 "머리: 값" 쌍을 " / "로 잇습니다. 세로 병합한 값은 행마다
      다시 적어, 한 줄만 떼어 읽어도 뜻이 통하게 합니다.
    """
    grid = table.grid()
    full = {c.row for c in table.cells if c.col == 0 and c.colspan >= table.cols}
    lines: list[str] = []
    header: list[str] | None = None
    for r, row in enumerate(grid):
        if r in full:
            lines.append(row[0])
            continue
        if header is None:
            header = row
            continue
        pairs = []
        for k, value in enumerate(row):
            if k and row[k - 1] == value and header[k - 1] == header[k]:
                continue
            pairs.append(f"{header[k]}: {value}" if header[k] else value)
        lines.append(" / ".join(pairs))
    return [x for x in lines if x]


def blocks_text(blocks: list[Block]) -> str:
    lines: list[str] = []
    for b in blocks:
        lines.extend(table_lines(b) if isinstance(b, Table) else [b])
    return "\n".join(lines)
