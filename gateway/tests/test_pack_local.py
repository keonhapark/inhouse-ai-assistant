"""팩 단위 외부 LLM 금지(#384, pack.yaml model_policy_override: local_only, 계약 #387)."""

import dataclasses
import json
import shutil

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from gateway.main import create_app
from gateway.registry import Registry

from .conftest import PACK, ROOT, FakeLiteLLM

MSG = [{"role": "user", "content": "규정 알려 줘"}]


@pytest.fixture
def local_pack(tmp_path):
    pack = tmp_path / "pack"
    shutil.copytree(PACK, pack)
    doc = yaml.safe_load((pack / "pack.yaml").read_text(encoding="utf-8"))
    doc["model_policy_override"] = "local_only"
    (pack / "pack.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return pack


@pytest.fixture
def lp(settings, fake_erp, issuer, local_pack):
    llm = FakeLiteLLM()
    app = create_app(dataclasses.replace(settings, pack_dir=local_pack), erp_transport=httpx.ASGITransport(app=fake_erp),
                     issuer=issuer, llm_transport=httpx.MockTransport(llm))
    with TestClient(app) as c:
        c.app_ref, c.llm = app, llm
        yield c


def _token(c, agent_id, cid="conv-p"):
    from gateway.registry import Requester

    app = c.app_ref
    return app.state.issuer.issue(Requester("E0001", "u", "staff", ("employee",), ()),
                                  app.state.registry.get(agent_id), cid).token


def _external_ok_in_pack():
    agents = yaml.safe_load((PACK / "agents.yaml").read_text(encoding="utf-8"))["agents"]
    return next(a["id"] for a in agents if a["model_policy"]["mode"] == "external_allowed" and a["stage"] == 1)


def _models(c):
    return [json.loads(q.content)["model"] for q in c.llm.requests]


def test_registry_reads_override_and_marks_every_agent_local_only(local_pack):
    reg = Registry.load(local_pack, ROOT / "contracts")
    assert reg.pack_local_only is True
    assert {a.model_policy["mode"] for a in reg.all()} == {"local_only"}
    assert Registry.load(PACK, ROOT / "contracts").pack_local_only is False


def test_external_request_with_token_goes_local(lp):
    tok = _token(lp, _external_ok_in_pack())
    r = lp.post("/v1/chat/completions", headers={"X-Delegation-Token": tok}, json={"model": "external", "messages": MSG})
    assert r.status_code == 200, r.text
    assert r.headers["x-egress-location"] == "local" and _models(lp) == ["local"]
    assert lp.app_ref.state.audit.egress.read_all() == []
    ev = lp.app_ref.state.audit.events.read_all()[-1]
    assert ev["model"]["location"] == "local" and "팩 외부 LLM 금지" in ev["detail"]


@pytest.mark.parametrize("condition", ["no_guard", "baseline_tools"])
def test_eval_conditions_that_turn_guards_off_still_stay_local(lp, condition):
    lp.app_ref.state.egress.condition_of = lambda _cid: condition
    tok = _token(lp, _external_ok_in_pack())
    r = lp.post("/v1/chat/completions", headers={"X-Delegation-Token": tok}, json={"model": "external", "messages": MSG})
    assert r.status_code == 200 and _models(lp) == ["local"]


@pytest.mark.parametrize("override,sent", [({"external": "external-sonnet"}, "local"),
                                           ({"external": "external-sonnet", "local": "local-exaone"}, "local-exaone")])
def test_model_override_cannot_reach_external(lp, override, sent):
    lp.app_ref.state.egress.override_of = lambda _cid: override
    tok = _token(lp, _external_ok_in_pack())
    r = lp.post("/v1/chat/completions", headers={"X-Delegation-Token": tok}, json={"model": "external", "messages": MSG})
    assert r.status_code == 200 and _models(lp) == [sent]


def test_requesting_external_alias_directly_never_leaves(lp):
    tok = _token(lp, _external_ok_in_pack())
    lp.llm.external_mode = "down"   # 외부로 나갔다면 실패해 폴백했을 것
    for alias in ("external", "external-sonnet"):
        r = lp.post("/v1/chat/completions", headers={"X-Delegation-Token": tok}, json={"model": alias, "messages": MSG})
        assert r.status_code == 200
    assert all(not m.startswith("external") for m in _models(lp))


def test_tokenless_external_is_refused_even_in_eval_toolcall_stack(lp):
    lp.app_ref.state.egress.eval_toolcall = True
    r = lp.post("/v1/chat/completions", json={"model": "external", "messages": MSG})
    assert r.status_code == 403 and r.json()["type"] == "urn:problem:model-policy"
    assert lp.llm.requests == []


def test_agent_lists_show_local_only(lp):
    from .conftest import PASSWORD, _employees

    no = next(e["employee_no"] for e in _employees() if e["grade"] == "staff")
    tok = lp.post("/api/auth/login", json={"employeeNo": no, "password": PASSWORD}).json()["accessToken"]
    h = {"Authorization": f"Bearer {tok}"}
    assert {a["modelPolicy"] for a in lp.get("/api/agents", headers=h).json()["items"]} == {"local_only"}
    assert {e["modelPolicy"]["mode"] for e in lp.get("/api/agent-registry", headers=h).json()["items"]} == {"local_only"}
