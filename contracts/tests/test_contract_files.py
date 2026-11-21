"""계약 파일 자체의 형식과 서로의 참조를 검사합니다."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate as validate_openapi
from openapi_spec_validator.readers import read_from_filename

from tests.schema_check import validate, validate_file
from tools.check_packs import main as check_packs_main
from tools.common import CONTRACTS, PACKS, ROOT, load, openapi_operations

SPECS = sorted((CONTRACTS / "openapi").glob("*.yaml"))
SCHEMAS = ["events/audit.schema.json", "events/trace.schema.json", "eval/scenario.schema.json",
           "pack/pack.schema.json", "mcp/tools.schema.json", "auth/delegation-token.schema.json"]


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_openapi_is_valid(spec: Path) -> None:
    doc, url = read_from_filename(str(spec))
    validate_openapi(doc, base_uri=url)


@pytest.mark.parametrize("rel", SCHEMAS)
def test_json_schemas_are_valid(rel: str) -> None:
    Draft202012Validator.check_schema(load(CONTRACTS / rel))


def test_erp_write_operations_follow_common_rules() -> None:
    scopes = {s["id"] for s in load(CONTRACTS / "auth/scopes.json")["scopes"]}
    ops = openapi_operations(load(CONTRACTS / "openapi/erp.yaml"))
    for op_id, op in ops.items():
        if op.get("security") == []:  # 공개 경로(건강 확인, 로그인, 서비스 로그인, 평가 초기화)
            continue
        assert op.get("x-required-scope") in scopes, op_id
        if op.get("x-write"):
            refs = {p.get("$ref", "") for p in op.get("parameters", [])}
            assert "#/components/parameters/DryRun" in refs, op_id
            assert "#/components/parameters/IdempotencyKey" in refs, op_id
            assert "x-undo" in op, op_id
            assert "200" in op["responses"] and "201" in op["responses"], op_id


def test_packs_pass_checks(capsys) -> None:
    assert check_packs_main() == 0, capsys.readouterr().out


def test_fixtures_are_reproducible(tmp_path: Path) -> None:
    gen = PACKS / "manufacturing/fixtures/generate.py"
    before = {p.name: p.read_bytes() for p in gen.parent.glob("*.json")}
    subprocess.run([sys.executable, str(gen)], check=True, capture_output=True)
    after = {p.name: p.read_bytes() for p in gen.parent.glob("*.json")}
    assert before == after, "고정 데이터를 다시 만들면 내용이 달라집니다(시드·Faker 판 확인)"


def test_pack_scenarios_follow_schema() -> None:
    files = sorted(PACKS.glob("*/scenarios/*.json"))
    assert files
    for f in files:
        validate_file("eval/scenario.schema.json", json.loads(f.read_text(encoding="utf-8")))


def test_example_events_follow_schema() -> None:
    validate_file("events/audit.schema.json", {
        "eventId": "evt_1", "occurredAt": "2026-11-20T10:00:00+09:00", "source": "gateway",
        "kind": "llm.request", "actor": {"employeeId": "E0016", "viaDelegationToken": True, "agentId": "hr"},
        "conversationId": "cnv_1", "model": {"name": "qwen3.5:9b", "location": "local", "externalSent": False,
                                             "redactions": 0}, "result": "ok"})
    validate_file("events/trace.schema.json", {
        "traceId": "0" * 32, "spanId": "1" * 16, "parentSpanId": None, "service": "agent", "name": "route",
        "startedAt": "2026-11-20T10:00:00+09:00", "durationMs": 120.5, "status": "ok",
        "llm": {"model": "qwen3.5:9b", "location": "local", "inputTokens": 512, "outputTokens": 20,
                "costUsd": 0, "cached": False}})


def test_ops_examples_follow_schema() -> None:
    counts = {"calls": 12, "blocked": {"total": 2, "byCode": {"trust_violation": 1, "policy_denied": 1}},
              "llmRequests": {"local": 9, "external": 3}, "externalCostUsd": 0.0042, "unpricedRequests": 0}
    metrics = {
        "since": "2026-11-20T00:00:00+09:00", "until": "2026-11-21T00:00:00+09:00", "totals": counts,
        "agents": [{"agentId": "assistant", "agentName": "전사 비서", **counts}],
        "routing": {"total": 12, "byMethod": {"llm": 7, "keyword": 3, "fallback": 1, "explicit": 1}},
        "budgets": {"period": "month", "periodStart": "2026-11-01T00:00:00+09:00",
                    "agents": [{"id": "assistant", "limitUsd": 20, "usedUsd": 0.0042, "exceeded": False}],
                    "units": [{"id": "mgmt", "name": "경영지원본부", "limitUsd": 15, "usedUsd": 0.0042}]},
    }
    validate("openapi/gateway.yaml", "OpsMetrics", metrics)
    validate("openapi/gateway.yaml", "OpsMetrics", {**metrics, "budgets": None})
    with pytest.raises(AssertionError):
        validate("openapi/gateway.yaml", "OpsCounts", {**counts, "blocked": {"total": 1, "byCode": {"unknown": 1}}})

    validate("openapi/gateway.yaml", "EgressRecord", {
        "recordId": "egr_1", "at": "2026-11-20T10:00:00+09:00", "agentId": "assistant", "agentName": "전사 비서",
        "conversationId": "cnv_1", "actorId": "E0007", "model": "anthropic/claude-haiku-5-5",
        "usage": {"promptTokens": 120, "completionTokens": 30}, "costUsd": 0.000027,
        "messages": [{"role": "user", "content": "[전화번호]로 회의 안내 보내 줘"}],
        "redactions": [{"entity": "KR_PHONE", "placeholder": "[전화번호]", "messageIndex": 0, "start": 0, "end": 6}]})
def _override(o: dict) -> dict:
    """팩의 인자 조건 when {arg, gt}는 등록부에서 when=arg_gt와 arg·gt 필드로 씁니다."""
    if isinstance(o["when"], dict):
        return {"tool": o["tool"], "when": "arg_gt", **o["when"], "action": o["action"]}
    return o


def test_agent_registry_matches_pack() -> None:
    """팩 agents.yaml의 항목을 등록부 스키마로 옮길 수 있어야 합니다(gateway 구현과 같은 변환)."""
    tools = {t["name"]: t for t in load(CONTRACTS / "mcp/tools.json")["tools"]}
    for pack in sorted(p for p in PACKS.iterdir() if (p / "agents.yaml").exists()):
        for a in load(pack / "agents.yaml")["agents"]:
            rp = a["risk_policy"]
            entry = {
                "id": a["id"], "name": a["name"], "version": a["version"], "stage": a["stage"],
                "ownerUnitId": a["owner_unit"], "ownerUnitName": None, "description": a["description"],
                "callable": True, "callableBy": a["callable_by"],
                "tools": [{"name": n, "risk": tools[n]["risk"]} for n in a["tools"]],
                "allowedRisk": a["allowed_risk"], "docScopes": a.get("doc_scopes", []),
                "modelPolicy": a["model_policy"],
                "riskPolicy": {"read": rp["read"], "reversibleWrite": rp["reversible_write"],
                               "irreversible": rp["irreversible"], "overrides": [_override(o) for o in rp.get("overrides", [])]},
                "routingKeywords": a.get("routing", {}).get("keywords", []),
            }
            validate("openapi/gateway.yaml", "AgentRegistryEntry", entry)


def test_no_human_only_operation_is_a_tool() -> None:
    ops = openapi_operations(load(CONTRACTS / "openapi/erp.yaml"))
    for t in load(CONTRACTS / "mcp/tools.json")["tools"]:
        if t["backend"]["service"] == "erp":
            assert not ops[t["backend"]["operationId"]].get("x-human-only"), t["name"]


def test_root_is_repo() -> None:
    assert (ROOT / "packs").is_dir() and (ROOT / "contracts").is_dir()


def test_fake_erp_eval_reset(monkeypatch) -> None:
    """평가 초기화는 ERP_EVAL_RESET=1일 때만 있고, 상태를 팩 고정 데이터로 되돌립니다."""
    from fastapi.testclient import TestClient

    from fakes.erp.app import create_app

    pack = PACKS / "manufacturing"
    monkeypatch.delenv("ERP_EVAL_RESET", raising=False)
    with TestClient(create_app(pack), base_url="http://fake/api/v1") as c:
        assert c.post("/_eval/reset").status_code == 404

    monkeypatch.setenv("ERP_EVAL_RESET", "1")
    app = create_app(pack)
    with TestClient(app, base_url="http://fake/api/v1") as c:
        st = app.state.erp
        st.employees.pop(next(iter(st.employees)))
        assert c.post("/_eval/reset").status_code == 204
        assert len(st.employees) == len(load(pack / "fixtures/employees.json")["employees"])


def test_pack_budgets_are_checked(tmp_path) -> None:
    """선택 파일 budgets.yaml: 스키마와 에이전트·부서 참조를 검사합니다."""
    import shutil

    from tools.check_packs import check_pack

    pack = tmp_path / "manufacturing"
    shutil.copytree(PACKS / "manufacturing", pack)
    assert check_pack(pack) == []
    (pack / "budgets.yaml").write_text("period: week\n", encoding="utf-8")
    assert any("budgets.yaml" in e for e in check_pack(pack))
    (pack / "budgets.yaml").write_text("period: month\nagents: {nobody: 1}\nunits: {nowhere: 1}\n",
                                       encoding="utf-8")
    errs = check_pack(pack)
    assert any("nobody" in e for e in errs) and any("nowhere" in e for e in errs)
    (pack / "budgets.yaml").unlink()
    assert check_pack(pack) == []          # 파일이 없어도 됩니다


def test_pack_erp_roles_are_checked(tmp_path) -> None:
    """선택 항목 org.yaml erp_roles: 없는 역할을 가리키면 잡고, 항목이 없어도 됩니다."""
    import re
    import shutil

    from tools.check_packs import check_pack

    pack = tmp_path / "manufacturing"
    shutil.copytree(PACKS / "manufacturing", pack)
    org = pack / "org.yaml"
    text = org.read_text(encoding="utf-8")
    org.write_text(text.replace("  auditor: auditor\n", "  auditor: nobody\n", 1), encoding="utf-8")
    assert any("erp_roles.auditor" in e for e in check_pack(pack))
    org.write_text(re.sub(r"(?m)^erp_roles:\n(  .*\n)+", "", text), encoding="utf-8")
    assert check_pack(pack) == []          # 항목이 없으면 기본값(hr_staff, auditor)


def test_pack_amount_product_of_is_checked(tmp_path) -> None:
    """양식 선택 항목 amount_product_of: 없는 필드나 정수가 아닌 필드를 가리키면 잡습니다."""
    import shutil

    from tools.check_packs import check_pack

    pack = tmp_path / "manufacturing"
    shutil.copytree(PACKS / "manufacturing", pack)
    forms = pack / "forms.yaml"
    text = forms.read_text(encoding="utf-8")
    forms.write_text(text.replace("amount_product_of: [quantity, unit_price]", "amount_product_of: [quantity, reason]"),
                     encoding="utf-8")
    assert any("amount_product_of 'reason'" in e for e in check_pack(pack))
