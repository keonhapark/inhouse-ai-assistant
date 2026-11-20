"""문서를 검색 단위(청크)로 나눕니다.

- 법령·생성 규정: 조문 하나가 청크 하나입니다. 조문이 `max_chars`보다 길면 항(①②…) 경계에서 나누고,
  `article`에 항 범위를 붙입니다(예: "제15조(연가 일수) 제2항~제3항").
- 예규 절: 절이 길면 "(1)", "(2)" 같은 항목 경계에서 나눕니다.
- 경계로 나눠도 긴 덩어리는 줄 단위, 그래도 길면 글자 단위로 자릅니다.

청크 본문은 원문 조각 그대로입니다. 인용 대조(quote가 원문에 있는지)가 이 본문을 기준으로 하기 때문입니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rag.corpus import Document, Section

MAX_CHARS = 700
_PARAGRAPH = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_ITEM = re.compile(r"^\((\d+)\)")


@dataclass(frozen=True)
class Chunk:
    id: str  # "<문서 ID>#<순번>"
    doc_id: str
    title: str
    article: str | None
    text: str
    trust: str
    acl_tags: frozenset[str]


def _marker(line: str) -> tuple[str, int] | None:
    """줄머리 표시의 종류와 번호. 항(①)은 ("para", 1), 항목((1))은 ("item", 1)."""
    if line[:1] and line[0] in _PARAGRAPH:
        return "para", _PARAGRAPH.index(line[0]) + 1
    if m := _ITEM.match(line):
        return "item", int(m.group(1))
    return None


def _label(kind: str, n: int) -> str:
    return f"제{n}항" if kind == "para" else f"({n})"


def _units(text: str) -> list[tuple[str | None, str]]:
    """본문을 항·항목 경계로 나눕니다. 첫 경계 앞의 글은 표시 없는 단위입니다.

    한 절에서는 한 종류의 표시만 경계로 씁니다. 항목((1))이 있으면 항목만 씁니다. 예규에서는 ①이
    표나 사례 기호로도 쓰이기 때문입니다. 번호는 앞 경계보다 클 때만 경계로 봅니다.
    """
    lines = text.split("\n")
    marks = [_marker(x) for x in lines]
    kind = "item" if any(m and m[0] == "item" for m in marks) else "para"
    units: list[tuple[str | None, list[str]]] = []
    last = 0
    for line, mark in zip(lines, marks, strict=True):
        if mark and mark[0] == kind and mark[1] > last:
            last = mark[1]
            units.append((_label(kind, mark[1]), [line]))
        elif not units:
            units.append((None, [line]))
        else:
            units[-1][1].append(line)
    return [(k, "\n".join(body)) for k, body in units]


def _hard_split(text: str, max_chars: int) -> list[str]:
    parts: list[str] = []
    buf = ""
    for line in text.split("\n"):
        while len(line) > max_chars:
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(line[:max_chars])
            line = line[max_chars:]
        if buf and len(buf) + 1 + len(line) > max_chars:
            parts.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        parts.append(buf)
    return parts


def _span(keys: list[str | None]) -> str | None:
    named = [k for k in keys if k]
    if not named:
        return None
    return named[0] if named[0] == named[-1] else f"{named[0]}~{named[-1]}"


def split_section(section: Section, max_chars: int = MAX_CHARS) -> list[tuple[str | None, str]]:
    """절 하나를 (article, 본문) 목록으로 나눕니다."""
    base = section.article
    if len(section.text) <= max_chars:
        return [(base, section.text)]
    # 긴 항은 잘게 자르되, 잘린 조각도 같은 항 표시를 가집니다.
    pieces: list[tuple[str | None, str]] = []
    for key, body in _units(section.text):
        pieces.extend((key, p) for p in (_hard_split(body, max_chars) if len(body) > max_chars else [body]))
    # 이웃한 조각은 max_chars 안에서 합칩니다.
    groups: list[tuple[list[str | None], list[str]]] = []
    for key, body in pieces:
        if groups and sum(len(b) + 1 for b in groups[-1][1]) + len(body) <= max_chars:
            groups[-1][0].append(key)
            groups[-1][1].append(body)
        else:
            groups.append(([key], [body]))
    out = []
    for keys, bodies in groups:
        body = "\n".join(bodies)
        span = _span(keys)
        article = " ".join(x for x in (base, span) if x) or None
        out.append((article, body))
    return out


def chunk_documents(docs: list[Document], max_chars: int = MAX_CHARS) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in docs:
        n = 0
        for section in doc.sections:
            for article, body in split_section(section, max_chars):
                n += 1
                chunks.append(
                    Chunk(
                        id=f"{doc.id}#{n}",
                        doc_id=doc.id,
                        title=doc.title,
                        article=article,
                        text=body,
                        trust=doc.trust,
                        acl_tags=frozenset(doc.acl_tags),
                    )
                )
    return chunks
