"""문서 파기(기획서 우려 14). 원문을 지우면 청크·벡터·임베딩 캐시를 함께 지웁니다.

파기한 문서 ID는 파기 목록 파일(`RAG_PURGE_FILE`, 없으면 캐시 폴더의 `purged.txt`)에 한 줄씩 남깁니다.
본문의 원본(팩·템플릿·고정본)은 저장소에 있어 다시 시작하면 다시 읽히므로, 시작할 때 이 목록의 문서를 빼고
색인합니다. 목록에는 문서 ID만 쓰고 본문은 쓰지 않습니다.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

from rag.search import SearchIndex, index_text


class PurgeList:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def ids(self) -> set[str]:
        if not self.path.exists():
            return set()
        return {x.strip() for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()}

    def add(self, doc_id: str) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(doc_id + "\n")


@dataclass(frozen=True)
class PurgeResult:
    doc_id: str
    chunks: int
    cache_entries: int

    def detail(self) -> str:
        return f"docId={self.doc_id}; 청크·벡터 {self.chunks}개, 임베딩 캐시 {self.cache_entries}개 지움"


def purge_document(index: SearchIndex, doc_id: str, purge_list: PurgeList) -> PurgeResult | None:
    """색인에 없는 문서면 None. 목록에 먼저 적고 지웁니다. 지우는 도중 멈춰도 다시 시작하면 빠지게 하려는 것입니다."""
    if not any(c.doc_id == doc_id for c in index.chunks):
        return None
    purge_list.add(doc_id)
    removed = index.remove_document(doc_id)
    forget = getattr(index.embedder, "forget", None)
    cache = 0
    if forget is not None:
        # 남은 청크와 글이 똑같은 항목은 남깁니다(남은 문서가 쓰는 벡터).
        cache = forget({index_text(c) for c in removed} - index.indexed_texts())
    return PurgeResult(doc_id, len(removed), cache)
