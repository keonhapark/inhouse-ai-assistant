"""보고서 통계(eval/protocol.md 5절). 표준 라이브러리만 씁니다.

- 비율 구간: Wilson 점수 구간, Clopper-Pearson 정확 구간
- 짝 비교 차이 구간: Newcombe(1998) method 10. 두 비율의 Wilson 구간과 짝 사이 상관(phi)으로 만듭니다.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

Z95 = 1.959963984540054


@dataclass(frozen=True)
class Interval:
    low: float
    high: float


def wilson(x: int, n: int, z: float = Z95) -> Interval:
    if n == 0:
        return Interval(0.0, 1.0)
    p = x / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return Interval(max(0.0, centre - half), min(1.0, centre + half))


def _binom_cdf(x: int, n: int, p: float) -> float:
    """P(X <= x), X ~ Bin(n, p)."""
    if p <= 0:
        return 1.0
    if p >= 1:
        return 1.0 if x >= n else 0.0
    lp, lq = math.log(p), math.log1p(-p)
    total = 0.0
    for k in range(0, x + 1):
        total += math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * lp + (n - k) * lq)
    return min(1.0, total)


def _bisect(f, lo: float = 0.0, hi: float = 1.0, iters: int = 100) -> float:
    """f가 [lo, hi]에서 단조이고 부호가 바뀌는 점."""
    flo = f(lo)
    for _ in range(iters):
        mid = (lo + hi) / 2
        if (f(mid) > 0) == (flo > 0):
            lo, flo = mid, f(mid)
        else:
            hi = mid
    return (lo + hi) / 2


def clopper_pearson(x: int, n: int, alpha: float = 0.05) -> Interval:
    """양측 (1-alpha) 정확 구간. x=0이면 상한은 1-(alpha/2)^(1/n)입니다."""
    if n == 0:
        return Interval(0.0, 1.0)
    low = 0.0 if x == 0 else _bisect(lambda p: (1 - _binom_cdf(x - 1, n, p)) - alpha / 2)
    high = 1.0 if x == n else _bisect(lambda p: _binom_cdf(x, n, p) - alpha / 2)
    return Interval(low, high)


@dataclass(frozen=True)
class PairedDiff:
    n: int
    p1: float
    p2: float
    diff: float  # p1 - p2
    interval: Interval


def newcombe_paired(pairs: Iterable[tuple[bool, bool]], z: float = Z95) -> PairedDiff:
    """짝지은 이진 결과(조건1, 조건2)로 p1-p2와 95% 구간(Newcombe 1998, method 10)을 냅니다."""
    a = b = c = d = 0
    for x, y in pairs:
        if x and y:
            a += 1
        elif x:
            b += 1
        elif y:
            c += 1
        else:
            d += 1
    n = a + b + c + d
    if n == 0:
        return PairedDiff(0, 0.0, 0.0, 0.0, Interval(-1.0, 1.0))
    p1, p2 = (a + b) / n, (a + c) / n
    w1, w2 = wilson(a + b, n, z), wilson(a + c, n, z)
    denom = (a + b) * (c + d) * (a + c) * (b + d)
    # phi의 연속성 보정: ad-bc가 양수면 n/2를 빼고 0 아래로 내리지 않습니다(Newcombe 1998 method 10,
    # StatsDirect 짝 비율 도움말의 구현과 같음)
    num = a * d - b * c
    if num > 0:
        num = max(num - n / 2, 0)
    phi = 0.0 if denom == 0 else num / math.sqrt(denom)
    diff = p1 - p2
    dl = math.sqrt(max(0.0, (p1 - w1.low) ** 2 - 2 * phi * (p1 - w1.low) * (w2.high - p2) + (w2.high - p2) ** 2))
    du = math.sqrt(max(0.0, (w1.high - p1) ** 2 - 2 * phi * (w1.high - p1) * (p2 - w2.low) + (p2 - w2.low) ** 2))
    return PairedDiff(n, p1, p2, diff, Interval(max(-1.0, diff - dl), min(1.0, diff + du)))


def pass_k(runs_by_scenario: dict[str, list[bool]], k: int) -> tuple[int, int]:
    """회차 k번이 모두 통과한 시나리오 수와 평가한 시나리오 수. 회차가 k번보다 적은 시나리오는 빼지 않고 실패로 셉니다."""
    passed = sum(1 for runs in runs_by_scenario.values() if len(runs) >= k and all(runs[:k]))
    return passed, len(runs_by_scenario)


def percentile(values: list[float], q: float) -> float | None:
    """선형 보간 백분위수(q는 0~100)."""
    if not values:
        return None
    s = sorted(values)
    pos = (len(s) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)
