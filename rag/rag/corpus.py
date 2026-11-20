"""문서 본문 모으기.

- 공개 규정(`source.type: law_open_api`): `corpus/law/<문서 ID>.json` 고정본(`python -m rag.lawfetch`로 만듦)
- 생성 문서(`source.type: generated`): `templates/<문서 ID>.md`를 팩 값으로 채움(`rag.generate`)

문서마다 조문(또는 절) 단위의 `Section` 목록을 가집니다. ACL 태그와 신뢰 등급은 팩 `docs.yaml`이 기준입니다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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
class Document:
    id: str
    title: str
    kind: str
    acl_tags: tuple[str, ...]
    trust: str
    stage: int
    source: dict[str, Any]
    sections: tuple[Section, ...]


class MissingBody(Exception):
    """docs.yaml에 있는 문서의 본문을 찾지 못했습니다."""


def _sections(raw: list[dict[str, Any]]) -> tuple[Section, ...]:
    return tuple(Section(s.get("label"), s.get("heading"), s["text"]) for s in raw)


def load_law_copy(doc_id: str, law_dir: Path = LAW_DIR) -> dict[str, Any]:
    path = law_dir / f"{doc_id}.json"
    if not path.exists():
        raise MissingBody(f"{doc_id}: 고정본 {path}가 없습니다(python -m rag.lawfetch)")
    return json.loads(path.read_text(encoding="utf-8"))


def load_documents(pack: Pack, *, stage: int | None = None, law_dir: Path = LAW_DIR) -> list[Document]:
    """팩 문서 목록의 본문을 모읍니다. `stage`를 주면 그 단계까지의 문서만 씁니다."""
    docs: list[Document] = []
    for entry in pack.documents:
        if stage is not None and entry["stage"] > stage:
            continue
        source = dict(entry["source"])
        kind = source["type"]
        if kind == "law_open_api":
            copy = load_law_copy(entry["id"], law_dir)
            if copy["id"] != entry["id"]:
                raise MissingBody(f"{entry['id']}: 고정본의 문서 ID가 {copy['id']}입니다")
            # 출처 유형·라이선스는 docs.yaml이 기준이고, 고정본은 주소·시행일·조회일만 더합니다.
            source = {**copy["source"], **source}
            title = copy["title"]
            sections = _sections(copy["sections"])
        elif kind == "generated":
            title = entry["title"]
            sections = _sections(render_document(entry["id"], pack))
        else:
            raise MissingBody(f"{entry['id']}: 아직 다루지 않는 출처 유형 {kind}")
        docs.append(
            Document(
                id=entry["id"],
                title=title,
                kind=entry["kind"],
                acl_tags=tuple(entry["acl_tags"]),
                trust=entry["trust"],
                stage=entry["stage"],
                source=source,
                sections=sections,
            )
        )
    return docs
