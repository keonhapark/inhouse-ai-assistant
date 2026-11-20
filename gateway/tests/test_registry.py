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
