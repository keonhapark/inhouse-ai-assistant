import pytest

from gateway.registry import Registry, Requester, grant_matches


def _who(**kw):
    base = dict(id="E1", unit_id="u1", grade="staff", roles=("employee",), access_tags=())
    return Requester(**{**base, **kw})


def test_grant_matches():
    assert grant_matches("all", _who())
    assert grant_matches({"roles": ["employee"]}, _who())
    assert grant_matches({"units": ["u1"]}, _who())
    assert grant_matches({"grades": ["staff"]}, _who())
    assert not grant_matches({"roles": ["x"], "units": ["u2"]}, _who())
    assert not grant_matches(None, _who())


def _agent(tools):
    return {"id": "a", "name": "에이", "callable_by": "all", "tools": tools, "doc_scopes": ["public"],
            "model_policy": {"mode": "local_only"}}


TOOLS = {"tools": [{"name": "t_read", "required_scope": "x:read"},
                   {"name": "t_decide", "required_scope": "x:decide"}]}
SCOPES = {"scopes": [{"id": "x:read"}, {"id": "x:decide", "human_only": True}]}


def test_human_only_scopes_never_enter_agent_scopes():
    reg = Registry({"agents": [_agent(["t_read", "t_decide"])]}, TOOLS, SCOPES)
    assert reg.get("a").scopes == ("x:read",)


def test_unknown_tool_fails_fast():
    with pytest.raises(ValueError):
        Registry({"agents": [_agent(["nope"])]}, TOOLS, SCOPES)


# ---------- 팩 단계(#170) ----------
def test_stage_follows_pack_yaml_and_env_only_overrides():
    import yaml

    from .conftest import PACK, ROOT

    agents = yaml.safe_load((PACK / "agents.yaml").read_text(encoding="utf-8"))["agents"]
    pack_stage = yaml.safe_load((PACK / "pack.yaml").read_text(encoding="utf-8"))["stage"]
    default = Registry.load(PACK, ROOT / "contracts")
    assert default.stage == pack_stage
    assert {a.id for a in default.all()} == {a["id"] for a in agents if a["stage"] <= pack_stage}
    one = Registry.load(PACK, ROOT / "contracts", stage=1)
    assert {a.id for a in one.all()} == {a["id"] for a in agents if a["stage"] <= 1}
    assert {a["id"] for a in agents if a["stage"] > 1} and not ({a["id"] for a in agents if a["stage"] > 1}
                                                              & {a.id for a in one.all()})


def test_later_stage_agent_is_hidden_and_gets_no_token(settings, fake_erp, issuer):
    import dataclasses

    import httpx
    import pytest as _pytest
    import yaml
    from fastapi.testclient import TestClient

    from gateway.main import create_app
    from gateway.problems import ProblemError

    from .conftest import PACK, PASSWORD, _employees

    later = [a["id"] for a in yaml.safe_load((PACK / "agents.yaml").read_text(encoding="utf-8"))["agents"]
             if a["stage"] > 1]
    app = create_app(dataclasses.replace(settings, pack_stage=1), erp_transport=httpx.ASGITransport(app=fake_erp),
                     issuer=issuer)
    no = next(e["employee_no"] for e in _employees() if e["grade"] == "staff")
    with TestClient(app) as c:
        tok = c.post("/api/auth/login", json={"employeeNo": no, "password": PASSWORD}).json()["accessToken"]
        ids = {a["id"] for a in c.get("/api/agents", headers={"Authorization": f"Bearer {tok}"}).json()["items"]}
        assert ids and not ids & set(later)
        assert c.post("/api/conversations", headers={"Authorization": f"Bearer {tok}"},
                      json={"agentId": later[0]}).status_code == 403
        import asyncio
        with _pytest.raises(ProblemError) as e:
            asyncio.run(app.state.delegation.issue(tok, later[0], "c"))
        assert e.value.status == 404
