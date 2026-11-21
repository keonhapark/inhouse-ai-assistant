"""LiteLLM 401 잡음 표시와 RCAEval 계열 통계 기준선(N-Sigma, BARO)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from incident import rcaeval_stats
from incident.app import DockerLogs, keyless_noise_on
from incident.baseline import rank
from incident.logs import Line, mark_keyless_noise, read_bundle

T0 = datetime(2026, 11, 20, 16, 0, tzinfo=timezone.utc)  # 유닉스 초가 15의 배수


def at(s: float) -> datetime:
    return T0 + timedelta(seconds=s)


def ts(s: float) -> str:
    return at(s).strftime("%Y-%m-%dT%H:%M:%S.%f000Z")


MISSING = ("litellm.AuthenticationError: Missing Anthropic API Key - A call is being made to anthropic but no key "
           "is set either in the environment variables or via params.")


def _keyless_block(s: float) -> list[str]:
    """묶음 litellm.log에 찍힌 모양 그대로(오류 줄, 빈 줄, model group 줄, 스택 추적, 예외 줄, 401 접근 로그)."""
    return [
        f"{ts(s)} 16:07:04 - LiteLLM Proxy:ERROR: common_request_processing.py:1839 - "
        f"litellm.proxy.proxy_server._handle_llm_api_exception(): Exception occured - {MISSING}",
        f"{ts(s)} ",
        f"{ts(s)} LiteLLM: model group 'external' failed with the error above. No fallback was attempted.",
        f"{ts(s)} Traceback (most recent call last):",
        f'{ts(s)}   File "/usr/local/lib/python3.12/site-packages/litellm/main.py", line 2871, in _complete_anthropic',
        f"{ts(s)}     raise litellm.AuthenticationError(",
        f"{ts(s)} litellm.exceptions.AuthenticationError: {MISSING}",
        f'{ts(s + 0.002)} INFO:     172.21.0.7:55130 - "POST /v1/chat/completions HTTP/1.1" 401 Unauthorized',
    ]


def _bundle(tmp_path, litellm: list[str], gateway: list[str]):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "litellm.log").write_text("\n".join(litellm) + "\n", encoding="utf-8")
    (tmp_path / "logs" / "gateway.log").write_text("\n".join(gateway) + "\n", encoding="utf-8")
    return tmp_path


def test_keyless_block_and_gateway_401_become_noise(tmp_path) -> None:
    b = _bundle(tmp_path, [
        f'{ts(9.9)} INFO:     172.21.0.7:55130 - "POST /v1/chat/completions HTTP/1.1" 200 OK',
        *_keyless_block(10),
        # 잘못된 키 배포 장애의 무늬는 그대로 둡니다
        f"{ts(30)} 16:10:13 - LiteLLM Proxy:ERROR: auth_exception_handler.py:207 - "
        "litellm.proxy.proxy_server.user_api_key_auth(): Exception occured - No connected db.",
    ], [
        f'{ts(10.003)} INFO:     172.21.0.5:44620 - "POST /v1/chat/completions HTTP/1.1" 401 Unauthorized',
        f'{ts(30.1)} INFO:     172.21.0.5:44620 - "POST /v1/chat/completions HTTP/1.1" 401 Unauthorized',
    ])
    lines = read_bundle(b)
    noise = [(x.service, x.text[:40]) for x in lines if x.level == "noise"]
    assert len([s for s, _ in noise if s == "litellm"]) == 5  # 오류 줄, model group, Traceback(스택 붙음), 예외 줄, 401
    assert [x.at for x in lines if x.level == "noise" and x.service == "gateway"] == [at(10.003)]
    kept = {(x.service, x.level) for x in lines if x.at >= at(29)}
    assert kept == {("litellm", "error"), ("gateway", "warn")}
    assert next(x for x in lines if x.at == at(9.9)).level == "info"
    # 끄면 아무것도 바꾸지 않습니다
    assert all(x.level != "noise" for x in read_bundle(b, keyless_noise=False))


def test_keyless_401_line_is_noise() -> None:
    lines = [Line(at(0), "litellm", "error", f"x {MISSING}"),
             Line(at(0.5), "litellm", "warn", '"POST /v1/chat/completions HTTP/1.1" 401 Unauthorized'),
             Line(at(0.5), "erp", "error", "HikariPool-1 - Connection is not available")]
    assert [x.level for x in mark_keyless_noise(lines)] == ["noise", "noise", "error"]


def test_real_failures_inside_keyless_window_are_kept() -> None:
    """키 없음 묶음 1초 안이라도 로컬 모델 실패, 500, 경로가 다른 401, 두 번째 401은 그대로 둡니다."""
    lines = [
        Line(at(0), "litellm", "error", f"LiteLLM Proxy:ERROR: ... {MISSING}"),
        Line(at(0.0001), "litellm", "info", "LiteLLM: model group 'external' failed with the error above."),
        Line(at(0.0002), "litellm", "error", "OllamaException - Connection refused"),
        Line(at(0.0003), "litellm", "info", "LiteLLM: model group 'local' failed with the error above."),
        Line(at(0.0004), "litellm", "error", "Traceback (most recent call last): | File ..."),
        Line(at(0.0005), "litellm", "error", f"litellm.exceptions.AuthenticationError: {MISSING}"),
        Line(at(0.001), "litellm", "warn", '"POST /v1/chat/completions HTTP/1.1" 401 Unauthorized'),
        Line(at(0.4), "litellm", "error", '"POST /v1/chat/completions HTTP/1.1" 500 Internal Server Error'),
        Line(at(0.5), "litellm", "warn", '"POST /v1/chat/completions HTTP/1.1" 401 Unauthorized'),
        Line(at(0.002), "gateway", "warn", '"POST /v1/chat/completions HTTP/1.1" 401 Unauthorized'),
        Line(at(0.3), "gateway", "warn", '"GET /api/v1/tickets HTTP/1.1" 401 Unauthorized'),
        Line(at(0.6), "gateway", "warn", '"POST /v1/chat/completions HTTP/1.1" 401 Unauthorized'),
    ]
    levels = [x.level for x in mark_keyless_noise(sorted(lines, key=lambda x: x.at))]
    by_text = {(x.service, x.text, x.at): lv for x, lv in zip(sorted(lines, key=lambda x: x.at), levels)}
    assert [by_text[(x.service, x.text, x.at)] for x in lines] == [
        "noise", "noise", "error", "info", "noise", "noise", "noise", "error", "warn",
        "noise", "warn", "warn"]


class _FakeStack:
    project = "iaa-s1"

    def logs(self, service: str, since: str, until: str) -> str:
        return "\n".join(_keyless_block(10)) + "\n" if service == "litellm" else ""


def test_docker_logs_marks_noise_unless_turned_off() -> None:
    on = DockerLogs(_FakeStack()).lines(at(0), at(60))
    off = DockerLogs(_FakeStack(), keyless_noise=False).lines(at(0), at(60))
    assert sum(x.level == "noise" for x in on) == 5
    assert all(x.level != "noise" for x in off)


@pytest.mark.parametrize(("value", "on"), [(None, True), ("1", True), ("0", False), ("false", False),
                                           (" OFF ", False), ("no", False)])
def test_keyless_noise_env(value: str | None, on: bool) -> None:
    assert keyless_noise_on({} if value is None else {"INCIDENT_KEYLESS_NOISE": value}) is on


def test_noise_does_not_count_as_template_increase() -> None:
    steady = [Line(at(s), svc, "info", "GET /api/v1/tickets 200 3ms") for s in range(0, 150, 3)
              for svc in ("erp", "litellm")]
    noise = [Line(at(s), "litellm", "noise", f"Traceback {MISSING}") for s in range(110, 150, 2)]
    pg = [Line(at(s), "postgres", "warn", "process 40 still waiting for AccessShareLock after 1000 ms")
          for s in range(110, 150, 5)]
    r = rank(steady + noise + pg, at(150), timedelta(seconds=45), since=at(0))
    assert [s for s, _ in r.ranking] == ["postgres"]


# ---------- RCAEval 계열 ----------

def test_scalers_match_sklearn_defaults() -> None:
    assert rcaeval_stats.robust([1, 2, 3, 4]) == (2.5, 1.5)  # 중앙값, 75% 3.25 - 25% 1.75
    assert rcaeval_stats.standard([2, 4]) == (3.0, 1.0)  # 모표준편차
    assert rcaeval_stats.standard([5, 5, 5]) == (5.0, 1.0)  # 척도 0 → 1
    assert rcaeval_stats.robust([7]) == (7, 1.0)


def test_log_series_bins_on_epoch_and_skips_noise_and_events() -> None:
    lines = [Line(at(1), "erp", "info", "GET /a 200 3ms"), Line(at(16), "erp", "info", "GET /b 200 4ms"),
             Line(at(17), "litellm", "noise", "Traceback"), Line(at(31), "erp", "error", "[container] die erp")]
    s = rcaeval_stats.log_series(lines)
    assert s.bins == [int(T0.timestamp()), int(T0.timestamp()) + 15]
    assert list(s.columns) == ["erp_1"] and s.columns["erp_1"] == [1, 1]


@pytest.mark.parametrize("method", ["nsigma", "baro"])
def test_rank_puts_new_error_service_first(method: str) -> None:
    steady = [Line(at(s), "gateway", "info", "POST /chat 200") for s in range(0, 120)]  # 칸마다 15줄(상수 → 빠짐)
    erp = [Line(at(s), "erp", "info", "GET /api/v1/tickets 200 3ms") for s in range(0, 120, 3)]
    burst = [Line(at(s), "erp", "error", "HikariPool-1 - Connection is not available, request timed out after 30000ms")
             for s in range(90, 120)]
    r = rcaeval_stats.rank(steady + erp + burst, at(90), method)
    assert r.ranking == ["erp"]
    assert all(not c.startswith("gateway") for c, _ in r.columns)
    assert r.columns[0][1] == 15.0  # 평소 0줄(척도 1) → 장애 칸 15줄


def test_rank_needs_both_sides() -> None:
    lines = [Line(at(s), "erp", "info", "x") for s in range(0, 30)]
    assert rcaeval_stats.rank(lines, at(60), "baro").ranking == []


def test_nsigma_and_baro_scale_differently() -> None:
    """평소 칸 [0,0,0,0,10,0], 장애 칸 [20,20]: N-Sigma 평균 1.667·표준편차 3.727 → 4.919, BARO 중앙값 0·IQR 0(→1) → 20."""
    per_bin = [0, 0, 0, 0, 10, 0, 20, 20]
    lines = [Line(at(s), "gateway", "info", "POST /chat 200") for s in range(0, 120, 15)]  # 칸 범위만 정함(상수)
    for b, n in enumerate(per_bin):
        lines += [Line(at(b * 15 + i * 0.5), "erp", "error", "HikariPool-1 - Connection is not available") for i in range(n)]
    scores = {m: rcaeval_stats.rank(lines, at(90), m).columns for m in ("nsigma", "baro")}
    assert scores["nsigma"][0][1] == 4.919
    assert scores["baro"][0][1] == 20.0
