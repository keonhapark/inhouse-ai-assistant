import json

import pytest
import yaml

from harness.paths import ROOT
from harness.scenario import ScenarioError, load_scenarios, substitute, validate_scenario
from tests.conftest import base_scenario, concern_scenario


def test_pack_scenarios_load():
    got = load_scenarios(ROOT / "packs/manufacturing/scenarios")
    assert {s["id"] for s in got} >= {"dev-normal-leave-half-day", "dev-concern-cross-dept-salary"}


def test_valid_minimal():
    validate_scenario(base_scenario())
    validate_scenario(concern_scenario())


@pytest.mark.parametrize("bad, words", [
    (base_scenario(set="weird"), "set"),
    ({k: v for k, v in concern_scenario().items() if k != "concernType"}, "concernType"),
    (concern_scenario(expect={"outcome": "blocked"}), "사고 판정 기준"),
    (base_scenario(concernType="leak"), "정상 시나리오에 concernType"),
    (concern_scenario(reactive=True), "reactive"),
    (base_scenario(expect={"outcome": "blocked"}), "expect.outcome이 blocked"),
    (base_scenario(expect={"requiredTools": ["no_such_tool"]}), "계약에 없는 도구"),
    (base_scenario(expect={"requiredTools": ["leave_request"], "forbiddenTools": ["leave_request"]}), "겹칩니다"),
    (base_scenario(setup=[{"as": "E0016", "operation": "x", "body": {"a": "${doc}"}}]), "${doc}"),
    (base_scenario(expect={"dbAssertions": [{"as": "E0016", "operation": "getApprovalDocument",
                                             "params": {"documentId": "${doc}"}, "jsonPath": "$.status",
                                             "op": "exists"}]}), "${doc}"),
    (base_scenario(expect={"approvable": [{"tool": "approval_withdraw", "after": {"id": "${doc}"}}]}), "approvable[0]"),
    (base_scenario(expect={"approvable": [{"tool": "nope_tool"}]}), "계약에 없는 도구"),
    (base_scenario(expect={"forbiddenTools": ["delegation_register"],
                           "approvable": [{"tool": "delegation_register"}]}), "금지 도구입니다"),
])
def test_rejects(bad, words):
    with pytest.raises(ScenarioError) as e:
        validate_scenario(bad)
    assert words in str(e.value)


def test_duplicate_ids(tmp_path):
    for name in ("a.json", "b.json"):
        (tmp_path / name).write_text(json.dumps(base_scenario()), encoding="utf-8")
    with pytest.raises(ScenarioError, match="겹칩니다"):
        load_scenarios(tmp_path)


def test_yaml_and_error_collection(tmp_path):
    (tmp_path / "ok.yaml").write_text("id: t-yaml\nversion: 1\npack: manufacturing\nset: dev\nkind: normal\n"
                                      "author: hand\nrequester: E0016\nturns: [{role: user, content: 안녕}]\n"
                                      "expect: {outcome: completed}\n", encoding="utf-8")
    assert load_scenarios(tmp_path)[0]["id"] == "t-yaml"
    (tmp_path / "bad1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "bad2.json").write_text(json.dumps(base_scenario(id="t2", set="x")), encoding="utf-8")
    with pytest.raises(ScenarioError) as e:
        load_scenarios(tmp_path)
    assert "bad1.json" in str(e.value) and "bad2.json" in str(e.value)


def test_substitute():
    assert substitute({"a": ["${x}/y"], "b": 1}, {"x": "D1"}) == {"a": ["D1/y"], "b": 1}
    with pytest.raises(KeyError):
        substitute("${nope}", {})


def test_list_file(tmp_path):
    (tmp_path / "many.yaml").write_text(yaml.safe_dump([base_scenario(id="t-a"), base_scenario(id="t-b"),
                                                        base_scenario(id="t-a")], allow_unicode=True),
                                        encoding="utf-8")
    with pytest.raises(ScenarioError) as e:
        load_scenarios(tmp_path)
    assert "many.yaml[2]: id t-a가 many.yaml[0]와 겹칩니다" in str(e.value)


def test_has_document_injection():
    from harness.scenario import has_document_injection

    assert has_document_injection({"injectedContent": [{"where": "tool_output"}, {"where": "document"}]})
    assert not has_document_injection({"injectedContent": [{"where": "tool_output"}]})
    assert not has_document_injection({})
