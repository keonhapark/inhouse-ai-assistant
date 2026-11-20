"""법령의 판(시행 기간) 적재와 기준일에 따른 판 선택."""

import json
import shutil
from datetime import date

import pytest

from rag.app import edition_policy
from rag.chunk import Chunk, chunk_documents
from rag.corpus import LAW_DIR, Edition, MissingBody, load_documents
from rag.embed import HashEmbedder
from rag.pack import load_pack
from rag.search import SearchIndex

DOC = "law-travel-expense"


@pytest.fixture(scope="module")
def pack():
    return load_pack()


@pytest.fixture(scope="module")
def editions(pack):
    return [d for d in load_documents(pack, stage=1) if d.id == DOC]


def test_옛_판_고정본을_같은_문서_ID의_판으로_시행일_순서대로_싣는다(editions):
    starts = [d.edition.effective_from for d in editions]
    assert starts == [date(2026, 1, 2), date(2026, 7, 1), date(2026, 10, 2)]


def test_판의_시행_끝날은_다음_판_시행_전날이고_마지막_판은_열려_있다(editions):
    ends = [d.edition.effective_to for d in editions]
    assert ends == [date(2026, 6, 30), date(2026, 10, 1), None]


def test_옛_판의_키와_청크_ID에는_시행일이_붙는다(editions):
    assert [d.key for d in editions] == [f"{DOC}@2026-01-02", f"{DOC}@2026-07-01", DOC]
    ids = {c.id for c in chunk_documents(editions)}
    assert f"{DOC}@2026-01-02#1" in ids and f"{DOC}#1" in ids
    assert len(ids) == len(chunk_documents(editions))


def test_청크는_판끼리_맞출_조문_번호를_가진다(editions):
    chunks = [c for c in chunk_documents(editions) if (c.section or "").startswith("제18조(")]
    assert {c.edition.effective_from for c in chunks} == {date(2026, 1, 2), date(2026, 7, 1), date(2026, 10, 2)}


def test_시행_기간_경계(editions):
    old = editions[0].edition
    assert old.in_force(date(2026, 1, 2)) and old.in_force(date(2026, 6, 30))
    assert not old.in_force(date(2026, 1, 1)) and not old.in_force(date(2026, 7, 1))
    assert Edition(date(2026, 10, 2), None, None).in_force(date(2099, 1, 1))


def test_시행일이_같은_판이_둘이면_알린다(pack, tmp_path):
    for f in LAW_DIR.glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    shutil.copy(tmp_path / f"{DOC}@2026-07-01.json", tmp_path / f"{DOC}@2026-07-01-copy.json")
    with pytest.raises(MissingBody, match="시행일이 같은"):
        load_documents(pack, law_dir=tmp_path)


def test_옛_판_고정본의_문서_ID가_다르면_알린다(pack, tmp_path):
    for f in LAW_DIR.glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    path = tmp_path / f"{DOC}@2026-01-02.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["id"] = "other"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(MissingBody):
        load_documents(pack, law_dir=tmp_path)


# ---------------------------------------------------------------- 판 선택

OLD = Edition(date(2026, 1, 2), date(2026, 6, 30), None)
NEW = Edition(date(2026, 7, 1), None, None)


def _chunk(cid: str, text: str, edition: Edition | None) -> Chunk:
    return Chunk(cid, "law", "여비 규정", "제18조", text, "trusted", frozenset({"public"}), edition, "제18조")


CHUNKS = [
    _chunk("law@2026-01-02#1", "근무지 내 출장은 같은 시 안의 출장이나 12킬로미터 미만 출장입니다.", OLD),
    _chunk("law#1", "근무지 내 출장은 다음 각 호의 출장입니다. 같은 시 안의 출장. 12킬로미터 미만 출장.", NEW),
    _chunk("gen#1", "출장 신청은 전날까지 합니다.", None),
]


def _index(editions="as_of", today=date(2026, 11, 20)):
    return SearchIndex(CHUNKS, HashEmbedder(), editions=editions, today=lambda: today)


@pytest.mark.parametrize("method", ["bm25", "vector", "hybrid"])
def test_기준일이_없으면_오늘_시행_중인_판만_찾는다(method):
    ids = {h.chunk.id for h in _index().search("근무지 내 출장", {"public"}, method, top_k=10)}
    assert "law#1" in ids and "law@2026-01-02#1" not in ids


def test_기준일을_주면_그날_시행_중인_판을_찾는다():
    ids = {h.chunk.id for h in _index().search("근무지 내 출장", {"public"}, "bm25", 10, as_of=date(2026, 3, 1))}
    assert "law@2026-01-02#1" in ids and "law#1" not in ids


def test_판이_없는_문서는_기준일과_상관없이_찾는다():
    ids = {h.chunk.id for h in _index().search("출장 신청", {"public"}, "bm25", 10, as_of=date(2000, 1, 1))}
    assert ids == {"gen#1"}


def test_all이면_판을_가리지_않는다():
    ids = {h.chunk.id for h in _index("all").search("근무지 내 출장", {"public"}, "bm25", 10)}
    assert {"law#1", "law@2026-01-02#1"} <= ids


def test_RAG_EDITIONS_환경_변수():
    assert edition_policy({}) == "as_of"
    assert edition_policy({"RAG_EDITIONS": ""}) == "as_of"
    assert edition_policy({"RAG_EDITIONS": "all"}) == "all"
    with pytest.raises(ValueError):
        edition_policy({"RAG_EDITIONS": "latest"})
