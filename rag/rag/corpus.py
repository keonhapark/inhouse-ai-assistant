"""문서 본문 모으기.

- 공개 규정(`source.type: law_open_api`): `corpus/law/<문서 ID>.json` 고정본(`python -m rag.lawfetch`로 만듦).
  옛 판 고정본 `corpus/law/<문서 ID>@<시행일>.json`이 있으면 같은 문서 ID의 다른 판으로 함께 싣습니다.
- 생성 문서(`source.type: generated`): `templates/<문서 ID>.md`를 팩 값으로 채움(`rag.generate`)

문서마다 조문(또는 절) 단위의 `Section` 목록을 가집니다. ACL 태그와 신뢰 등급은 팩 `docs.yaml`이 기준입니다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from rag.generate import render_document
from rag.pack import Pack

MODULE_ROOT = Path(__file__).resolve().parents[1]
LAW_DIR = MODULE_ROOT / "corpus" / "law"


@dataclass(frozen=True)
class Section:
    """조문 하나 또는 예규의 절 하나."""

    label: str | None  # 예: "제15조", "4. 가."
    heading: str | None  # 예: "연가일수"
    text: str

    @property
    def article(self) -> str | None:
        """계약의 `article` 표시. 제목이 있으면 붙입니다(예: "제15조(연가일수)")."""
        if self.label and self.heading:
            return f"{self.label}({self.heading})"
        return self.label or self.heading


@dataclass(frozen=True)
class Edition:
    """법령 한 판의 시행 기간. `effective_to`는 다음 판 시행 전날이고, 마지막 판이면 None입니다."""

    effective_from: date
    effective_to: date | None
    promulgation: str | None

    def in_force(self, on: date) -> bool:
        return self.effective_from <= on and (self.effective_to is None or on <= self.effective_to)


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    kind: str
    acl_tags: tuple[str, ...]
    trust: str
    stage: int
    source: dict[str, Any]
    sections: tuple[Section, ...]
    edition: Edition | None = None

    @property
    def key(self) -> str:
        """판까지 가르는 키. 마지막 판은 문서 ID 그대로, 옛 판은 "<문서 ID>@<시행일>"입니다."""
        if self.edition is None or self.edition.effective_to is None:
            return self.id
        return f"{self.id}@{self.edition.effective_from.isoformat()}"


class MissingBody(Exception):
    """docs.yaml에 있는 문서의 본문을 찾지 못했습니다."""


def _sections(raw: list[dict[str, Any]]) -> tuple[Section, ...]:
    return tuple(Section(s.get("label"), s.get("heading"), s["text"]) for s in raw)


def load_law_copy(doc_id: str, law_dir: Path = LAW_DIR) -> dict[str, Any]:
    path = law_dir / f"{doc_id}.json"
    if not path.exists():
        raise MissingBody(f"{doc_id}: 고정본 {path}가 없습니다(python -m rag.lawfetch)")
    return json.loads(path.read_text(encoding="utf-8"))


def load_law_editions(doc_id: str, law_dir: Path = LAW_DIR) -> list[dict[str, Any]]:
    """현행 고정본과 옛 판 고정본을 시행일 순서로 돌려줍니다."""
    copies = [load_law_copy(doc_id, law_dir)]
    copies += [json.loads(p.read_text(encoding="utf-8")) for p in sorted(law_dir.glob(f"{doc_id}@*.json"))]
    for c in copies:
        if c["id"] != doc_id:
            raise MissingBody(f"{doc_id}: 고정본의 문서 ID가 {c['id']}입니다")
    copies.sort(key=lambda c: c["source"]["effectiveDate"])
    dates = [c["source"]["effectiveDate"] for c in copies]
    if len(set(dates)) != len(dates):
        raise MissingBody(f"{doc_id}: 시행일이 같은 판이 둘 있습니다")
    return copies


def _editions(copies: list[dict[str, Any]]) -> list[Edition]:
    starts = [date.fromisoformat(c["source"]["effectiveDate"]) for c in copies]
    ends: list[date | None] = [s - timedelta(days=1) for s in starts[1:]]
    ends.append(None)
    return [
        Edition(start, end, c["source"].get("promulgation"))
        for c, start, end in zip(copies, starts, ends, strict=True)
    ]


def load_documents(pack: Pack, *, stage: int | None = None, law_dir: Path = LAW_DIR) -> list[Document]:
    """팩 문서 목록의 본문을 모읍니다. `stage`를 주면 그 단계까지의 문서만 씁니다."""
    docs: list[Document] = []
    for entry in pack.documents:
        if stage is not None and entry["stage"] > stage:
            continue
        source = dict(entry["source"])
        kind = source["type"]
        if kind == "law_open_api":
            copies = load_law_editions(entry["id"], law_dir)
            for copy, edition in zip(copies, _editions(copies), strict=True):
                # 출처 유형·라이선스는 docs.yaml이 기준이고, 고정본은 주소·시행일·조회일만 더합니다.
                docs.append(_document(entry, copy["title"], {**copy["source"], **source}, _sections(copy["sections"]), edition))
            continue
        if kind == "generated":
            docs.append(_document(entry, entry["title"], source, _sections(render_document(entry["id"], pack)), None))
            continue
        raise MissingBody(f"{entry['id']}: 아직 다루지 않는 출처 유형 {kind}")
    return docs


def _document(
    entry: dict[str, Any], title: str, source: dict[str, Any], sections: tuple[Section, ...], edition: Edition | None
) -> Document:
    return Document(
        id=entry["id"],
        title=title,
        kind=entry["kind"],
        acl_tags=tuple(entry["acl_tags"]),
        trust=entry["trust"],
        stage=entry["stage"],
        source=source,
        sections=sections,
        edition=edition,
    )
