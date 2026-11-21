"""도면 OCR + BM25 기준선(bench/drawing_ocr.py)의 흐름. OCR 엔진 없이 정답 글자(oracle)로 봅니다(#496)."""

import pytest

pytest.importorskip("PIL")  # 도면 생성기가 Pillow를 씁니다(--group ocr)

from bench.drawing_ocr import make_drawings, oracle_engine, run_baseline  # noqa: E402


def test_정답_글자를_주면_찾기와_채점이_모두_맞는다(tmp_path):
    truths = make_drawings(8, tmp_path)
    result = run_baseline(truths, tmp_path, oracle_engine())
    s = result["summary"]
    assert s["drawings"] == 8 and s["partTop1"] == 8 and s["partTop5"] == 8
    assert s["endToEndAllCorrect"] == 8 and s["ocrOnlyAllCorrect"] == 8
    assert s["endToEndItems"] == s["ocrOnlyItems"] == "48/48"


def test_글자를_잘못_읽으면_점수가_내려간다(tmp_path):
    truths = make_drawings(8, tmp_path)

    def noisy(image, truth):
        return [line.replace("DIA", "D1A") for line in oracle_engine()(image, truth)]  # 지름 표기를 틀리게 읽음

    s = run_baseline(truths, tmp_path, noisy)["summary"]
    assert s["partTop1"] == 8  # 부품 번호는 그대로라 찾기는 맞고
    assert s["ocrOnlyAllCorrect"] == 0 and s["endToEndAllCorrect"] == 0  # 읽기 점수가 내려갑니다


def test_도면을_만드는_시드가_같으면_정답이_같다(tmp_path):
    a = make_drawings(5, tmp_path / "a")
    b = make_drawings(5, tmp_path / "b")
    assert [t["part_no"] for t in a] == [t["part_no"] for t in b]
    assert len({t["part_no"] for t in a}) == 5
