"""#303 라우터 비교 어댑터(Laya·Jev)와 비교 스크립트. 실제 모델·외부 API는 부르지 않습니다(스텁)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

from agent_runtime.decision_router import JEV_URL, QUESTION, JevChooser, LayaChooser, criteria
from agent_runtime.registry import Registry
from tests.conftest import PACK_DIR

EVAL_DEV = Path(__file__).resolve().parents[1] / "eval_dev"


@pytest.fixture(scope="module")
def reg2() -> Registry:
    return Registry.load(PACK_DIR, stage=2)


def _compare():
    spec = importlib.util.spec_from_file_location("router_compare", EVAL_DEV / "router_compare.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["router_compare"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_criteria_lists_every_enabled_agent_with_examples(reg2: Registry) -> None:
    c = criteria(reg2)
    assert set(c) == {a.id for a in reg2.agents}
    hr = reg2.get("hr")
    assert c["hr"].startswith(hr.description) and hr.raw["routing"]["examples"][0] in c["hr"]


class FakeLaya:
    def __init__(self, answer: dict, route: str | None = None) -> None:
        self.answer = answer
        self.route = route
        self.calls: list[tuple] = []

    def predict(self, state, questions):
        self.calls.append((state, questions))
        out = {"answers": {QUESTION: self.answer}}
        if self.route:
            out["route"] = self.route
        return out


def test_laya_asks_a_choice_question_and_reads_answer(reg2: Registry) -> None:
    fake = FakeLaya({"choice": "hr", "probabilities": {"hr": 0.8, "assistant": 0.2}, "route": "auto"})
    loaded: list[str] = []
    chooser = LayaChooser(loader=lambda m: loaded.append(m) or fake)
    c = chooser.choose("다음 주 연차 쓸게", criteria(reg2))
    assert (c.agent_id, c.probabilities["hr"], c.review) == ("hr", 0.8, False)
    state, questions = fake.calls[0]
    assert state == {"body": "다음 주 연차 쓸게"}
    assert questions[QUESTION]["type"] == "choice" and set(questions[QUESTION]["criteria"]) == {a.id for a in reg2.agents}
    chooser.choose("또", criteria(reg2))
    assert loaded == ["convaiinnovations/laya-multilingual"]  # 모델은 한 번만 불러옴


def test_laya_review_and_unknown_choice(reg2: Registry) -> None:
    c = LayaChooser(loader=lambda m: FakeLaya({"choice": "legal"}, route="review")).choose("x", criteria(reg2))
    assert c.agent_id is None and c.review is True


def test_jev_request_and_response(reg2: Registry) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"model": "jev-1.14.0", "answers": {QUESTION: {
            "type": "choice", "choice": "finance", "confidence": 0.9, "probabilities": {"finance": 0.95}}},
            "usage": {"input_tokens": 410, "output_tokens": 12}})

    c = JevChooser(api_key="k-test", transport=httpx.MockTransport(handler)).choose("택시비 정산", criteria(reg2))
    assert (c.agent_id, c.confidence, c.model, c.input_tokens) == ("finance", 0.9, "jev-1.14.0", 410)
    [req] = seen
    assert str(req.url) == JEV_URL and req.headers["Authorization"] == "Bearer k-test"
    body = json.loads(req.content)
    assert body["model"] == "jev-1.14.0" and body["state"] == {"body": "택시비 정산"}
    assert body["questions"][QUESTION]["type"] == "choice"


def test_jev_needs_key_and_raises_on_http_error(reg2: Registry) -> None:
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        JevChooser(api_key="").choose("x", criteria(reg2))
    bad = JevChooser(api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(429, json={})))
    with pytest.raises(httpx.HTTPStatusError):
        bad.choose("x", criteria(reg2))


def test_compare_items_and_term_variants() -> None:
    mod = _compare()
    items = mod.load_items()
    normal = [i for i in items if i["source"] == "normal"]
    assert len(normal) == 80 and len([i for i in items if i["source"] == "router_stage2"]) == 17
    variants = [i for i in items if i["source"].endswith("+variant")]
    assert variants and all("대리 결재" in v["message"] and "대결" not in v["message"] for v in variants)


def test_compare_summary_counts_local_to_external(reg2: Registry) -> None:
    mod = _compare()
    base = {"source": "normal", "error": None, "latencyMs": 5, "inputTokens": None, "confidence": None}
    rows = [
        {**base, "method": "laya", "expected": "hr", "agent": "hr", "ambiguous": False},
        {**base, "method": "laya", "expected": "hr", "agent": "assistant", "ambiguous": True},
        {**base, "method": "laya", "expected": "hr", "agent": "assistant", "ambiguous": False},
        {**base, "method": "jev", "expected": "hr", "agent": "assistant", "confidence": 0.3, "inputTokens": 1000,
         "ambiguous": False},
    ]
    s = mod.summary(rows, reg2, jev_threshold=0.5)
    assert s["laya"]["correct"] == 1 and s["laya"]["local_to_external"] == 2
    assert s["laya"]["local_to_external_if_ambiguous_forced_local"] == 1
    assert s["jev"]["ambiguous"] == 1 and s["jev"]["local_to_external_if_ambiguous_forced_local"] == 0
    assert s["jev"]["cost_usd"] == pytest.approx(1000 / 1e6 * 0.042)


def test_compare_refuses_jev_without_allow_external(monkeypatch, tmp_path: Path) -> None:
    mod = _compare()
    monkeypatch.setattr(sys, "argv", ["x", "--methods", "jev", "--out", str(tmp_path / "o.jsonl")])
    with pytest.raises(SystemExit, match="allow-external"):
        mod.main()


def test_criteria_styles(reg2: Registry) -> None:
    hr = reg2.get("hr")
    assert criteria(reg2, "desc")["hr"] == hr.description
    assert criteria(reg2, "keywords")["hr"].startswith(hr.raw["routing"]["keywords"][0])
    with pytest.raises(ValueError):
        criteria(reg2, "nope")
