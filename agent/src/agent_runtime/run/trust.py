"""도구 출력의 신뢰 등급.

- rag(policy_search): 인용 문서가 모두 팩 docs.yaml에서 trust=trusted면 신뢰, 하나라도 아니면(모르는 문서 포함) 신뢰 불가
- erp: 다른 사람이 쓴 자유 문장(사유·제목·의견 등)이 있으면 신뢰 불가. 작성자 필드가 요청자와 같으면 본인이 쓴 글로 봅니다.
  작성자를 알 수 없는 자유 문장도 신뢰 불가입니다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

FREE_TEXT_KEYS = frozenset({"reason", "title", "comment", "memo", "content", "body", "description", "note", "message"})
AUTHOR_KEYS = ("requesterId", "delegatorId", "registeredBy", "reservedBy", "actorId", "authorId", "createdBy",
               "approverId")


def trusted_docs(pack_dir: Path) -> frozenset[str]:
    path = pack_dir / "docs.yaml"
    if not path.is_file():
        return frozenset()
    doc = yaml.safe_load(path.read_text("utf-8")) or {}
    return frozenset(d["id"] for d in doc.get("documents", []) if d.get("trust") == "trusted")


def output_trusted(service: str, data: Any, requester_id: str, trusted_doc_ids: frozenset[str]) -> bool:
    if service == "rag":
        cites = data.get("citations", []) if isinstance(data, dict) else []
        return all(isinstance(c, dict) and c.get("docId") in trusted_doc_ids for c in cites)
    return not _has_foreign_text(data, requester_id, ())


def _has_foreign_text(node: Any, requester_id: str, inherited: tuple[str, ...]) -> bool:
    """작성자 필드가 없는 하위 객체(예: 결재 문서의 fields)는 가장 가까운 상위 객체의 작성자를 물려받습니다."""
    if isinstance(node, list):
        return any(_has_foreign_text(x, requester_id, inherited) for x in node)
    if not isinstance(node, dict):
        return False
    authors = tuple(node[k] for k in AUTHOR_KEYS if isinstance(node.get(k), str)) or inherited
    texts = [k for k, v in node.items() if k in FREE_TEXT_KEYS and isinstance(v, str) and v.strip()]
    if texts and (not authors or any(a != requester_id for a in authors)):
        return True
    return any(_has_foreign_text(v, requester_id, authors) for v in node.values() if isinstance(v, (dict, list)))
