"""RCAEval 계열 통계 기준선(N-Sigma, BARO)의 로그 부분을 우리 묶음에 돌립니다.

RCAEval(Pham et al., https://github.com/phamquiluan/RCAEval, MIT License, Copyright (c) 2024 Luan Pham)의 두 곳을
옮겼습니다.

- 로그 시계열(`RCAEval/convert/derive.py`의 log_series): 줄 앞에 컨테이너 이름을 붙여 Drain3로 템플릿을 묶고,
  유닉스 시각 기준 15초 칸마다 `{서비스}_{템플릿 번호}` 열의 줄 수를 셉니다. 가림은 RCAEval 기본(UUID, IP, HEX, 숫자)입니다.
- 순위(`RCAEval/e2e/baro.py`의 mmnsigma·mmbaro 중 logts 부분): 모든 칸에서 값이 같은 열을 빼고, 주입 전 칸으로
  척도를 맞춘 뒤(N-Sigma는 평균·표준편차, BARO는 중앙값·사분위 범위) 주입 뒤 칸의 최댓값을 점수로 열을 줄 세웁니다.
  서비스 순위는 열 순위에서 서비스가 처음 나온 차례입니다.

RCAEval과 다른 점: sklearn·pandas 없이 같은 계산을 표준 라이브러리로 합니다. 지표(metric)·트레이스는 우리 묶음에
없어 쓰지 않습니다. 컨테이너 이벤트 줄([container])은 RCAEval의 logs.csv에 없는 출처라 넣지 않습니다.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from drain3 import TemplateMiner
from drain3.masking import MaskingInstruction
from drain3.template_miner_config import TemplateMinerConfig

from incident.logs import Line

BIN_SECONDS = 15

# RCAEval convert/derive.py DEFAULT_MASKS 그대로
_B, _E = r"((?<=[^A-Za-z0-9])|^)", r"((?=[^A-Za-z0-9])|$)"
DEFAULT_MASKS = [
    (_B + r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})" + _E, "UUID"),
    (_B + r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?)" + _E, "IP"),
    (_B + r"(0x[0-9a-fA-F]+)" + _E, "HEX"),
    (_B + r"([0-9a-fA-F]{16,})" + _E, "HEX"),
    (_B + r"([\-\+]?\d+(\.\d+)?)" + _E, "NUM"),
]
# sklearn preprocessing._handle_zeros_in_scale: 척도가 0에 가까우면 1로 둡니다(값이 한 가지인 평소 구간).
_ZERO_SCALE = 10 * 2.220446049250313e-16


@dataclass(frozen=True)
class LogSeries:
    bins: list[int]
    """칸 시작 시각(유닉스 초)"""
    columns: dict[str, list[int]]
    """`{서비스}_{템플릿 번호}` → 칸마다 줄 수"""
    templates: dict[str, str]


def log_series(lines: list[Line], bin_seconds: int = BIN_SECONDS) -> LogSeries:
    config = TemplateMinerConfig()
    config.profiling_enabled = False
    config.masking_instructions = [MaskingInstruction(p, m) for p, m in DEFAULT_MASKS]
    miner = TemplateMiner(config=config)
    keys: list[tuple[int, str]] = []
    for x in lines:
        if x.level == "noise" or x.text.startswith("[container]"):
            continue
        cid = miner.add_log_message(f"{x.service}_{x.text}")["cluster_id"]
        sec = int(x.at.timestamp())
        keys.append((sec - sec % bin_seconds, f"{x.service}_{cid}"))
    if not keys:
        return LogSeries([], {}, {})
    counts = Counter(keys)
    lo, hi = min(b for b, _ in keys), max(b for b, _ in keys)
    bins = list(range(lo, hi + 1, bin_seconds))
    columns = {c: [counts.get((b, c), 0) for b in bins] for c in dict.fromkeys(c for _, c in keys)}
    clusters = {c.cluster_id: c.get_template() for c in miner.drain.clusters}
    templates = {c: clusters[int(c.rsplit("_", 1)[1])] for c in columns}
    return LogSeries(bins, columns, templates)


def _percentile(values: list[float], q: float) -> float:
    """numpy percentile 기본(linear)과 같은 값."""
    s = sorted(values)
    pos = (len(s) - 1) * q / 100
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _scale(v: float) -> float:
    return 1.0 if v < _ZERO_SCALE else v


def standard(normal: list[float]) -> tuple[float, float]:
    """sklearn StandardScaler: 평균, 모표준편차(ddof=0)."""
    return statistics.fmean(normal), _scale(statistics.pstdev(normal))


def robust(normal: list[float]) -> tuple[float, float]:
    """sklearn RobustScaler 기본: 중앙값, 사분위 범위(25~75)."""
    return statistics.median(normal), _scale(_percentile(normal, 75) - _percentile(normal, 25))


SCALERS = {"nsigma": standard, "baro": robust}


@dataclass(frozen=True)
class StatResult:
    ranking: list[str]
    """서비스 순위"""
    columns: list[tuple[str, float]]
    """열 순위(열, 점수)"""


def rank(lines: list[Line], inject: datetime, method: str, bin_seconds: int = BIN_SECONDS) -> StatResult:
    """inject 앞 칸이 평소 구간, inject 뒤 칸이 장애 구간입니다(RCAEval: time < inject_time 이면 평소).
    lines는 분석에 쓸 범위(묶음 시작~신고 시각)만 줍니다."""
    series = log_series(lines, bin_seconds)
    cut = inject.timestamp()
    normal_idx = [i for i, b in enumerate(series.bins) if b < cut]
    anomal_idx = [i for i, b in enumerate(series.bins) if b >= cut]
    if not normal_idx or not anomal_idx:
        return StatResult([], [])
    scaler = SCALERS[method]
    scored = []
    for col, values in series.columns.items():
        if all(v == values[0] for v in values):  # RCAEval drop_constant
            continue
        center, scale = scaler([float(values[i]) for i in normal_idx])
        scored.append((col, round(max((values[i] - center) / scale for i in anomal_idx), 3)))
    scored.sort(key=lambda kv: kv[1], reverse=True)
    services: dict[str, None] = {}
    for col, _ in scored:
        services.setdefault(col.rsplit("_", 1)[0], None)
    return StatResult(list(services), scored)

