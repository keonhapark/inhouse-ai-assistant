"""분석기: 로그 읽기, 기준선(템플릿 변화·로그 끊김·유사 티켓), LLM 답 해석."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from incident.baseline import PastTicket, rank, similar_tickets, windows
from incident.llm import analyze, diagnostics, parse
from incident.logs import Line, read_events, read_service

T0 = datetime(2026, 11, 20, 16, 0, tzinfo=timezone.utc)


def at(s: float) -> datetime:
    return T0 + timedelta(seconds=s)


def ts(s: float) -> str:
    return at(s).strftime("%Y-%m-%dT%H:%M:%S.%f000Z")


def test_read_service_folds_stack_traces_and_marks_health(tmp_path) -> None:
    p = tmp_path / "erp.log"
    p.write_text("\n".join([
        f"{ts(1)} 2026-11-20T16:00:01.000Z ERROR 1 --- [erp] boom java.lang.IllegalStateException",
        f"{ts(1)} \tat io.inhouse.Foo.bar(Foo.java:1)",
        f'{ts(2)} INFO:     127.0.0.1:1 - "GET /health HTTP/1.1" 200 OK',
        f"{ts(3)} INFO access : GET /api/v1/tickets 200 12ms",
    ]) + "\n", encoding="utf-8")
    lines = read_service(p, "erp")
    assert [x.level for x in lines] == ["error", "heartbeat", "info"]
    assert "Foo.java" in lines[0].text and not lines[0].text.startswith("2026")


def test_read_events_drops_operator_actions(tmp_path) -> None:
    p = tmp_path / "docker-events.log"
    p.write_text("2026-11-20T16:00:01.000000Z pause litellm\n2026-11-20T16:00:02.000000Z die erp exitCode=137\n"
                 "2026-11-20T16:00:03.000000Z oom erp\n2026-11-20T16:00:04.000000Z kill postgres\n", encoding="utf-8")
    assert [x.text for x in read_events(p)] == ["[container] die erp exitCode=137", "[container] oom erp"]


def test_windows_use_available_start() -> None:
    before, during = windows(at(100), timedelta(seconds=45), since=at(30))
    assert (before.start, before.end, during.start, during.end) == (at(30), at(55), at(55), at(100))


def _steady(service: str, until: float, step: float = 5.0) -> list[Line]:
    return [Line(at(s), service, "heartbeat", "GET /health") for s in range(0, int(until), int(step))]


def test_new_errors_and_silence_rank_services() -> None:
    lines = _steady("gateway", 200) + _steady("rag", 60)  # rag는 60초부터 조용해짐
    lines += [Line(at(s), "erp", "info", "GET /api/v1/tickets 200 3ms") for s in range(0, 200, 2)]
    lines += [Line(at(s), "postgres", "warn", "process 40 still waiting for AccessShareLock after 1000 ms")
              for s in range(110, 140, 3)]
    r = rank(lines, at(150), timedelta(seconds=45), since=at(0))
    top = [s for s, _ in r.ranking]
    assert set(top[:2]) == {"postgres", "rag"}
    assert "gateway" not in top and "erp" not in top
    assert any(c.template == "<로그가 끊김>" and c.service == "rag" for c in r.changes)


def test_similar_tickets_vote_for_past_cause() -> None:
    history = [PastTicket("t1", "회의실 예약 화면이 멈춥니다 예약 버튼이 오래 걸립니다", "postgres", "lock_contention"),
               PastTicket("t2", "AI 비서가 답을 안 합니다", "litellm", "dependency_timeout")]
    sim = similar_tickets("회의실 예약이 오래 걸려 멈춥니다", history)
    assert sim[0].ticket.id == "t1"
    r = rank([], at(100), timedelta(seconds=45), "회의실 예약이 오래 걸려 멈춥니다", history, since=at(0))
    assert r.ranking[0][0] == "postgres"


def test_parse_keeps_known_distinct_services() -> None:
    raw = 'x {"candidates": [{"service": "postgres", "kind": "lock_contention", "reason": "r", "evidence": ["a"]},' \
          '{"service": "postgres", "kind": "x"}, {"service": "redis"}, {"service": "erp", "kind": "nope"}]} y'
    got = parse(raw)
    assert [(c.service, c.kind) for c in got] == [("postgres", "lock_contention"), ("erp", None)]
    assert parse("답 못 함") == []


def test_analyze_sends_local_alias_without_thinking() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"candidates": [{"service": "rag", "kind": "data_corruption", "reason": "r", "evidence": []}]}'}}]})

    r = rank([], at(100), timedelta(seconds=45), since=at(0))
    out = analyze("http://gw", diagnostics(r, "규정 검색이 안 됩니다"), transport=httpx.MockTransport(handler))
    assert [c.service for c in out.candidates] == ["rag"]
    assert seen["model"] == "local" and seen["reasoning_effort"] == "none" and seen["max_tokens"] > 0
    assert "규정 검색이 안 됩니다" in seen["messages"][1]["content"]


def test_parse_survives_truncated_answer_and_string_evidence() -> None:
    raw = ('{"candidates": [{"service": "postgres", "kind": "dependency_down", "reason": "r", "evidence": "die postgres"},'
           ' {"service": "erp", "kind": "resource_exhaustion", "reason": "잘린')
    got = parse(raw)
    assert [(c.service, c.evidence) for c in got] == [("postgres", ["die postgres"])]
