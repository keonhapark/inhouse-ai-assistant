"""LLM 없는 기준선(기획서 표 ③): 로그 템플릿 빈도 변화 + 유사 과거 티켓.

1. 서비스 로그를 Drain3로 템플릿(가변 값을 <*>로 바꾼 문장 틀)으로 묶습니다.
2. 분석 구간과 바로 앞 같은 길이의 기준 구간에서 템플릿별 줄 수를 세고, 늘어난 정도를 점수로 씁니다.
   오류·경고 수준과 기준 구간에 없던 새 템플릿은 가중치를 더 줍니다.
3. 서비스별로 템플릿 점수를 더해 순위를 냅니다.
4. 과거 티켓(원인이 밝혀진 것) 중 글자 n-gram이 비슷한 것의 원인 서비스에 표를 더합니다.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

from incident.logs import Line

LEVEL_WEIGHT = {"error": 3.0, "warn": 2.0, "info": 1.0}
NEW_TEMPLATE_BONUS = 1.5


@dataclass(frozen=True)
class TemplateChange:
    service: str
    template: str
    level: str
    before: int
    during: int
    score: float
    example: str


@dataclass
class Window:
    start: datetime
    end: datetime

    def __contains__(self, t: datetime) -> bool:
        return self.start <= t < self.end


def windows(at: datetime, length: timedelta, since: datetime | None = None) -> tuple[Window, Window]:
    """(기준 구간, 분석 구간). 분석 구간은 at 직전 length, 기준 구간은 그 앞 length입니다.
    since(로그가 있는 첫 시각)를 주면 기준 구간은 since부터 분석 구간 앞까지입니다(묶음처럼 앞쪽 로그가 짧을 때)."""
    start = since if since is not None and since < at - length else at - 2 * length
    return Window(start, at - length), Window(at - length, at)


def miner() -> TemplateMiner:
    cfg = TemplateMinerConfig()
    cfg.profiling_enabled = False
    cfg.drain_sim_th = 0.5
    cfg.drain_depth = 4
    cfg.masking_instructions = []
    return TemplateMiner(config=cfg)


# Drain3에 넣기 전에 흔한 가변 값(시각, ID, 숫자)을 미리 가립니다.
MASKS = (
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "<UUID>"),
    (re.compile(r"\b(conv|tkt|act|evt|doc|rsv|tcm|tsc|dlg)_[0-9a-z]+\b"), "<ID>"),
    (re.compile(r"\b\d+\.\d+\.\d+\.\d+(:\d+)?\b"), "<IP>"),
    (re.compile(r"@[0-9a-f]{5,}\b"), "@<HEX>"),
    (re.compile(r"\b\d+(\.\d+)?(ms)?\b"), "<NUM>"),
)


def mask(text: str) -> str:
    for pat, rep in MASKS:
        text = pat.sub(rep, text)
    return text


def template_changes(lines: list[Line], before: Window, during: Window) -> list[TemplateChange]:
    m = miner()
    counts: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
    level: dict[tuple[str, int], str] = {}
    example: dict[tuple[str, int], str] = {}
    for line in lines:
        if line.level == "heartbeat" or (line.at not in before and line.at not in during):
            continue
        r = m.add_log_message(f"{line.service} {mask(line.text)}")
        key = (line.service, r["cluster_id"])
        counts[key][0 if line.at in before else 1] += 1
        if LEVEL_WEIGHT[line.level] >= LEVEL_WEIGHT.get(level.get(key, "info"), 1):
            level[key] = line.level
            if line.at in during or key not in example:
                example[key] = line.text
    clusters = {c.cluster_id: c.get_template() for c in m.drain.clusters}
    out = []
    for (svc, cid), (b, d) in counts.items():
        if d <= b:
            continue
        lv = level[(svc, cid)]
        score = math.log((d + 1) / (b + 1)) * LEVEL_WEIGHT[lv] * (NEW_TEMPLATE_BONUS if b == 0 else 1.0)
        out.append(TemplateChange(svc, clusters[cid].removeprefix(f"{svc} "), lv, b, d, round(score, 3),
                                  example[(svc, cid)]))
    return sorted(out, key=lambda c: c.score, reverse=True)


SILENCE_WEIGHT = 3.0
SILENCE_MIN_EXPECTED = 3.0
SILENCE_RATIO = 0.2


def silences(lines: list[Line], before: Window, during: Window) -> list[TemplateChange]:
    """기준 구간 빠르기로 보아 분석 구간에 줄이 3줄 이상 나왔어야 하는데 그 20% 이하만 나온 서비스.
    멈추거나 죽은 컨테이너는 오류도 남기지 못해 템플릿 변화로는 안 보입니다(헬스 검사 줄도 셉니다)."""
    span_b = (before.end - before.start).total_seconds()
    span_d = (during.end - during.start).total_seconds()
    if span_b <= 0 or span_d <= 0:
        return []
    count: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for line in lines:
        if line.service.startswith("docker") or line.text.startswith("[container]"):
            continue
        if line.at in before:
            count[line.service][0] += 1
        elif line.at in during:
            count[line.service][1] += 1
    out = []
    for svc, (b, d) in count.items():
        expected = b / span_b * span_d
        if expected >= SILENCE_MIN_EXPECTED and d <= expected * SILENCE_RATIO:
            score = SILENCE_WEIGHT * math.log(expected + 1)
            out.append(TemplateChange(svc, "<로그가 끊김>", "error", b, d, round(score, 3),
                                      f"기준 구간 {b}줄(분석 구간 길이로 {expected:.0f}줄 기대) → 분석 구간 {d}줄"))
    return out


def service_scores(changes: list[TemplateChange]) -> dict[str, float]:
    scores: dict[str, float] = defaultdict(float)
    for c in changes:
        scores[c.service] += c.score
    return dict(scores)


# ---------- 유사 과거 티켓 ----------

def ngrams(text: str, n: int = 2) -> Counter[str]:
    s = re.sub(r"\s+", " ", text.lower()).strip()
    return Counter(s[i:i + n] for i in range(max(0, len(s) - n + 1)))


def cosine(a: Counter[str], b: Counter[str]) -> float:
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


@dataclass(frozen=True)
class PastTicket:
    id: str
    text: str
    root_service: str
    kind: str


@dataclass(frozen=True)
class SimilarTicket:
    ticket: PastTicket
    similarity: float


def similar_tickets(text: str, history: list[PastTicket], k: int = 3) -> list[SimilarTicket]:
    q = ngrams(text)
    scored = [SimilarTicket(t, round(cosine(q, ngrams(t.text)), 3)) for t in history]
    return sorted((s for s in scored if s.similarity > 0), key=lambda s: s.similarity, reverse=True)[:k]


# ---------- 합치기 ----------

@dataclass
class BaselineResult:
    ranking: list[tuple[str, float]]
    changes: list[TemplateChange]
    similar: list[SimilarTicket] = field(default_factory=list)


def rank(lines: list[Line], at: datetime, length: timedelta, ticket_text: str | None = None,
         history: list[PastTicket] | None = None, ticket_weight: float = 0.5,
         since: datetime | None = None) -> BaselineResult:
    """서비스 순위. 로그 점수를 합이 1이 되게 나누고, 유사 티켓이 있으면 원인 서비스에 유사도 × ticket_weight를 더합니다."""
    before, during = windows(at, length, since)
    changes = sorted(template_changes(lines, before, during) + silences(lines, before, during),
                     key=lambda c: c.score, reverse=True)
    scores = service_scores(changes)
    total = sum(scores.values()) or 1.0
    combined = {s: v / total for s, v in scores.items()}
    similar = similar_tickets(ticket_text, history) if ticket_text and history else []
    for s in similar:
        combined[s.ticket.root_service] = combined.get(s.ticket.root_service, 0.0) + s.similarity * ticket_weight
    ranking = sorted(combined.items(), key=lambda kv: kv[1], reverse=True)
    return BaselineResult([(s, round(v, 3)) for s, v in ranking], changes, similar)
