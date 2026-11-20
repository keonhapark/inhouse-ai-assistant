import pytest

from harness.stats import clopper_pearson, newcombe_paired, pass_k, percentile, wilson


def test_wilson_known_value():
    # 10/20: Wilson 95% 구간 0.2993~0.7007
    w = wilson(10, 20)
    assert w.low == pytest.approx(0.2993, abs=1e-4) and w.high == pytest.approx(0.7007, abs=1e-4)


def test_clopper_pearson_zero_matches_protocol():
    # 프로토콜 5-2: 0/15 약 22%, 0/75 약 5%
    assert clopper_pearson(0, 15).high == pytest.approx(1 - 0.025 ** (1 / 15), abs=1e-9)
    assert clopper_pearson(0, 15).high == pytest.approx(0.218, abs=1e-3)
    assert clopper_pearson(0, 75).high == pytest.approx(0.048, abs=1e-3)
    assert clopper_pearson(0, 15).low == 0.0


def test_clopper_pearson_known_value():
    # 5/20: 정확 구간 0.0866~0.4910 (R binom.test)
    cp = clopper_pearson(5, 20)
    assert cp.low == pytest.approx(0.0866, abs=1e-4) and cp.high == pytest.approx(0.4910, abs=1e-4)
    assert clopper_pearson(20, 20).high == 1.0


def test_newcombe_paired_published_example():
    # https://statsdirect.co.uk/help/proportions/paired.htm 의 예(Armitage·Berry 1994): n=50, 둘 다 20, 첫째만 12, 둘째만 2
    # Newcombe 점수 구간 0.056156~0.329207
    pairs = [(True, True)] * 20 + [(True, False)] * 12 + [(False, True)] * 2 + [(False, False)] * 16
    r = newcombe_paired(pairs)
    assert r.diff == pytest.approx(0.2)
    assert r.interval.low == pytest.approx(0.056156, abs=1e-5)
    assert r.interval.high == pytest.approx(0.329207, abs=1e-5)


def test_newcombe_all_zero_and_empty():
    r = newcombe_paired([(False, False)] * 15)
    assert r.diff == 0 and r.interval.low < 0 < r.interval.high
    assert newcombe_paired([]).n == 0


def test_pass_k_counts_short_runs_as_fail():
    assert pass_k({"a": [True, True, True], "b": [True, False, True], "c": [True, True]}, 3) == (1, 3)


def test_percentile():
    assert percentile([], 50) is None
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([1, 2, 3, 4, 5], 95) == pytest.approx(4.8)
