from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tests.llm_cassette import BudgetExceeded, Cassette, CassetteMiss, request_key

BODY = {"model": "m", "messages": [{"role": "user", "content": "안녕"}], "temperature": 0}


def _post(cassette: Cassette) -> httpx.Response:
    with httpx.Client(transport=cassette, base_url="http://x.invalid/v1") as c:
        return c.post("/chat/completions", json=BODY)


def test_replay_hit(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text(json.dumps({request_key(BODY): {"content": "답"}}), "utf-8")
    resp = _post(Cassette(path, record=False, budget=0))
    assert resp.json()["choices"][0]["message"]["content"] == "답"


def test_replay_miss_fails(tmp_path: Path) -> None:
    with pytest.raises(CassetteMiss):
        _post(Cassette(tmp_path / "c.json", record=False, budget=10))


def test_record_budget_is_enforced(tmp_path: Path) -> None:
    with pytest.raises(BudgetExceeded):
        _post(Cassette(tmp_path / "c.json", record=True, budget=0))


def test_key_ignores_non_prompt_fields() -> None:
    assert request_key(BODY) == request_key(dict(BODY, temperature=1, reasoning_effort="none"))


def _cassette_with_real(path: Path, budget: int, real: httpx.MockTransport) -> Cassette:
    c = Cassette(path, record=True, budget=budget)
    c._real = real
    return c


def test_record_saves_and_hits_do_not_spend_budget(tmp_path: Path) -> None:
    calls: list[int] = []

    def real(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "녹화"}}]})

    path = tmp_path / "c.json"
    c = _cassette_with_real(path, 1, httpx.MockTransport(real))
    assert _post(c).json()["choices"][0]["message"]["content"] == "녹화"
    assert _post(c).json()["choices"][0]["message"]["content"] == "녹화"  # 두 번째는 녹화본에서
    assert (len(calls), c.real_calls) == (1, 1)
    c.save()
    saved = json.loads(path.read_text("utf-8"))
    assert saved[request_key(BODY)]["content"] == "녹화"
    assert _post(Cassette(path, record=False, budget=0)).status_code == 200


def test_record_does_not_save_failed_response(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    c = _cassette_with_real(path, 5, httpx.MockTransport(lambda req: httpx.Response(503)))
    assert _post(c).status_code == 503
    c.save()
    assert not path.exists()
