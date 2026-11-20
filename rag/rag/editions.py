"""판끼리 같은 조문을 맞춰, 인용한 조문이 다른 판에서 글이 다르면 그 판의 조문을 함께 돌려줍니다(충돌 둘 다 표시).

조문은 절 표시의 번호 부분("제18조")으로 맞춥니다. 개정으로 조문 제목이 바뀌어도 같은 조문으로 보기 위해서입니다.
글을 비교할 때는 판마다 그 조문의 청크를 순서대로 이어 붙인 글을 씁니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from rag.chunk import Chunk
from rag.corpus import Edition


def section_key(section: str | None) -> str | None:
    return section.split("(")[0] if section else None


def edition_body(edition: Edition, today: date) -> dict[str, Any]:
    return {
        "effectiveFrom": edition.effective_from.isoformat(),
        "effectiveTo": edition.effective_to.isoformat() if edition.effective_to else None,
        "current": edition.in_force(today),
        "promulgation": edition.promulgation,
    }


@dataclass(frozen=True)
class Revision:
    doc_id: str
    title: str
    article: str | None
    text: str
    edition: Edition
    relation: str  # "earlier" | "later"

    def body(self, today: date) -> dict[str, Any]:
        return {
            "docId": self.doc_id,
            "title": self.title,
            "article": self.article,
            "text": self.text,
            "edition": edition_body(self.edition, today),
            "relation": self.relation,
        }


class EditionBook:
    """(문서 ID, 조문 번호) → 판별 조문 글."""

    def __init__(self, chunks: list[Chunk]):
        self._texts: dict[tuple[str, str], dict[Edition, list[Chunk]]] = {}
        for c in chunks:
            key = section_key(c.section)
            if c.edition is None or key is None:
                continue
            self._texts.setdefault((c.doc_id, key), {}).setdefault(c.edition, []).append(c)

    def revisions(self, cited: Chunk) -> list[Revision]:
        """인용한 판 바로 앞뒤로 글이 다른 판을 하나씩(가까운 것) 돌려줍니다. 앞 판, 뒤 판 순서입니다."""
        key = section_key(cited.section)
        if cited.edition is None or key is None:
            return []
        by_edition = self._texts.get((cited.doc_id, key), {})
        mine = _text(by_edition.get(cited.edition, []))
        ordered = sorted(by_edition, key=lambda e: e.effective_from)
        earlier = [e for e in ordered if e.effective_from < cited.edition.effective_from]
        later = [e for e in ordered if e.effective_from > cited.edition.effective_from]
        out = []
        for relation, candidates in (("earlier", reversed(earlier)), ("later", later)):
            for e in candidates:
                chunks = by_edition[e]
                if _text(chunks) != mine:
                    out.append(Revision(cited.doc_id, chunks[0].title, chunks[0].section, _text(chunks), e, relation))
                    break
        return out


def _text(chunks: list[Chunk]) -> str:
    return "\n".join(c.text for c in chunks)
