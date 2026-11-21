"""규모 시험 스크립트(bench/scale.py)의 늘린 문서와 셈."""

from bench.scale import base_documents, is_gold, percentile, questions, scaled_chunks, synthetic_documents
from rag.editions import section_key


def gold():
    return {(q["doc"], q["article"]) for q in questions()}


def test_배수만큼_문서를_늘린다():
    base = base_documents()
    assert len(synthetic_documents(base, 1, gold())) == 0
    assert len(synthetic_documents(base, 3, gold())) == 2 * len(base)


def test_늘린_문서에는_정답_조문이_없고_ID가_겹치지_않는다():
    base = base_documents()
    extra = synthetic_documents(base, 3, gold())
    origin = {d.id: d.id.split("~")[0] for d in extra}
    for d in extra:
        assert all((origin[d.id], section_key(s.article)) not in gold() for s in d.sections)
    ids = [d.id for d in base + extra]
    assert len(ids) == len(set(ids))


def test_늘린_문서는_원래_문서의_ACL을_따르고_판이_없다():
    base = {d.id: d for d in base_documents()}
    for d in synthetic_documents(list(base.values()), 2, gold()):
        assert d.acl_tags == base[d.id.split("~")[0]].acl_tags and d.edition is None


def test_씨앗이_같으면_같은_문서를_만든다():
    base = base_documents()
    a = synthetic_documents(base, 2, gold())
    b = synthetic_documents(base, 2, gold())
    assert [s.text for d in a for s in d.sections] == [s.text for d in b for s in d.sections]


def test_정답_청크는_배수와_상관없이_원래_문서에만_있다():
    for scale in (1, 2):
        chunks, _ = scaled_chunks(scale)
        for q in questions():
            golds = [c for c in chunks if is_gold(c, q)]
            assert golds and all("~" not in c.doc_id for c in golds), q["id"]


def test_백분위():
    values = list(range(1, 101))
    assert percentile(values, 50) == 50 and percentile(values, 95) == 95 and percentile([3.0], 95) == 3.0


def test_문서_수를_맞추고_그룹_태그를_붙인다():
    base = base_documents()
    chunks, n = scaled_chunks(1, docs=len(base) + 25, tags=7)
    assert n == len(base) + 25
    groups = {t for c in chunks for t in c.acl_tags if t.startswith("grp-")}
    assert groups and groups <= {f"grp-{i:03d}" for i in range(7)}
    assert all(not any(t.startswith("grp-") for t in c.acl_tags) for c in chunks if "~" not in c.doc_id)


def test_태그를_주지_않으면_원래_문서의_ACL을_따른다():
    base = base_documents()
    chunks, _ = scaled_chunks(1, docs=len(base) + 5)
    assert all(not t.startswith("grp-") for c in chunks for t in c.acl_tags)


def test_권한_확인은_범위_밖_청크가_없다고_센다():
    from bench.scale import check_permissions, user_scopes
    from rag.embed import HashEmbedder
    from rag.search import SearchIndex

    chunks, _ = scaled_chunks(1, docs=len(base_documents()) + 60, tags=20)
    index = SearchIndex(chunks, HashEmbedder())
    scope = user_scopes(20, 3)
    result = check_permissions(index, questions(), scope, 20)
    assert result["leakedHits"] == 0 and result["goldLeaksRestricted"] == 0
    assert result["restrictedGroups"] == 3 and result["allowedChunks"] > 0
