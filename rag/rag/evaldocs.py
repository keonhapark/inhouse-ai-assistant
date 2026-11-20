"""평가용 적재(eval 시나리오 전용). 둘 다 환경 변수로 파일을 줄 때만 동작합니다.

- `RAG_MARKERS_FILE`(contracts/eval/markers.schema.json): 생성 문서의 모든 청크 끝에 문서별 표지 문자열을 한 줄씩 넣습니다.
  어느 청크가 새더라도 답·근거에 표지가 나오게 해, 권한 밖 문서 유출을 표지로 셀 수 있게 하려는 것입니다.
  절이 아니라 청크에 넣는 것은 긴 절이 여러 청크로 나뉘면 절 끝 표지가 마지막 청크에만 남기 때문입니다.
  표지가 여럿이면 청크마다 돌아가며 넣습니다.
- `RAG_EXTRA_DOCS`(contracts/eval/injected-docs.schema.json): 간접 주입 시나리오용 문서를 팩 문서에 더합니다.
  trust는 언제나 untrusted이고, ACL은 `accessTag` 하나입니다.

파일은 계약 스키마로 확인하고, 틀리거나 경로에 파일이 없으면 시작 때 실패합니다. 조용히 건너뛰면 평가가 표지 없이
돌아 유출을 0건으로 잴 수 있기 때문입니다. 환경 변수가 없거나 빈 값이면 꺼짐입니다. compose가 `${VAR:-}`로 늘
넘기므로 빈 값을 오류로 보면 평가를 하지 않는 기본 실행이 시작하지 못합니다(#90).
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from rag.chunk import Chunk, chunk_documents
from rag.corpus import Document, Section
from rag.pack import REPO_ROOT, Pack

SCHEMA_DIR = REPO_ROOT / "contracts" / "eval"
MARKER_PREFIX = "관리 표지: "


class EvalDocsError(Exception):
    pass


def _load(path: Path, schema_name: str) -> dict[str, Any]:
    if not path.exists():
        raise EvalDocsError(f"{path}가 없습니다")
    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    if errors:
        raise EvalDocsError(f"{path.name}가 {schema_name}에 맞지 않습니다: {errors[0].message}")
    return data


def check_marker_targets(docs: list[Document], markers: dict[str, list[str]]) -> None:
    by_id = {d.id: d for d in docs}
    for doc_id in markers:
        doc = by_id.get(doc_id)
        if doc is None:
            raise EvalDocsError(f"표지 대상 문서 {doc_id}가 적재한 문서에 없습니다")
        if doc.source.get("type") != "generated":
            raise EvalDocsError(f"표지는 생성 문서에만 넣습니다: {doc_id}")


def mark_chunks(chunks: list[Chunk], markers: dict[str, list[str]]) -> list[Chunk]:
    seen: dict[str, int] = {}
    out = []
    for c in chunks:
        marks = markers.get(c.doc_id)
        if not marks:
            out.append(c)
            continue
        i = seen.get(c.doc_id, 0)
        seen[c.doc_id] = i + 1
        out.append(replace(c, text=f"{c.text}\n{MARKER_PREFIX}{marks[i % len(marks)]}"))
    return out


def injected_documents(data: dict[str, Any], pack: Pack) -> list[Document]:
    tags = {t["id"] for t in pack.org.get("access_tags", [])}
    taken: set[str] = set()
    docs = []
    for item in data["documents"]:
        if item["accessTag"] not in tags:
            raise EvalDocsError(f"{item['docId']}: 팩에 없는 접근 태그 {item['accessTag']}")
        if item["docId"] in taken:
            raise EvalDocsError(f"주입 문서 ID가 겹칩니다: {item['docId']}")
        taken.add(item["docId"])
        docs.append(
            Document(
                id=item["docId"],
                title=item["title"],
                kind="ticket",
                acl_tags=(item["accessTag"],),
                trust="untrusted",
                stage=1,
                source={"type": "injected", "license": "평가용 생성 문서"},
                sections=(Section(None, None, item["body"]),),
            )
        )
    return docs


def _path(env: dict[str, str], name: str) -> Path | None:
    value = env.get(name, "").strip()
    return Path(value) if value else None


def apply_eval_files(docs: list[Document], pack: Pack, env: dict[str, str] | None = None) -> list[Chunk]:
    """팩 문서에 평가 파일을 반영해 청크 목록을 돌려줍니다."""
    env = dict(os.environ) if env is None else env
    if path := _path(env, "RAG_EXTRA_DOCS"):
        extra = injected_documents(_load(path, "injected-docs.schema.json"), pack)
        clash = {d.id for d in extra} & {d.id for d in docs}
        if clash:
            raise EvalDocsError(f"주입 문서 ID가 팩 문서와 겹칩니다: {sorted(clash)}")
        docs = docs + extra
    chunks = chunk_documents(docs)
    if path := _path(env, "RAG_MARKERS_FILE"):
        markers = _load(path, "markers.schema.json")["markers"]
        check_marker_targets(docs, markers)
        chunks = mark_chunks(chunks, markers)
    return chunks
