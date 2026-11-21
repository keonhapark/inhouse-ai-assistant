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
SCHEMAS = ["events/audit.schema.json", "events/trace.schema.json", "eval/scenario.schema.json", "eval/report.schema.json",
           "pack/pack.schema.json", "mcp/tools.schema.json", "auth/delegation-token.schema.json"]


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_openapi_is_valid(spec: Path) -> None:
    doc, url = read_from_filename(str(spec))
    validate_openapi(doc, base_uri=url)


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_openapi_has_no_split_descriptions(spec: Path) -> None:
    """흐름 매핑({... description: a, b})의 따옴표 없는 쉼표가 설명을 잘라 값 없는 키를 만들지 않았는지 봅니다."""
    found: list[str] = []

    def walk(o: object, path: str) -> None:
        if isinstance(o, dict):
            if isinstance(o.get("description"), str):
                # default·example은 null이 정당한 값입니다
                found.extend(f"{path}/{k}" for k, v in o.items() if v is None and k not in ("default", "example"))
            for k, v in o.items():
                walk(v, f"{path}/{k}")
        elif isinstance(o, list):
            for i, x in enumerate(o):
                walk(x, f"{path}[{i}]")

    walk(load(spec), "")
    assert not found, "설명이 쉼표에서 잘렸습니다(따옴표로 감쌉니다): " + ", ".join(found)


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


@pytest.mark.parametrize("gen", sorted(PACKS.glob("*/fixtures/generate.py")), ids=lambda p: p.parts[-3])
def test_fixtures_are_reproducible(gen: Path) -> None:
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
    from tools.pack_tools import form_tools

    public = {t["name"]: t for t in load(CONTRACTS / "mcp/tools.json")["tools"]}
    for pack in sorted(p for p in PACKS.iterdir() if (p / "agents.yaml").exists()):
        # 팩 양식 도구(#397)도 등록부에 같은 방식으로 들어갑니다.
        tools = {**{t["name"]: t for t in form_tools(load(pack / "forms.yaml"))}, **public}
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


def test_eval_reports_follow_schema() -> None:
    """커밋된 평가 보고서 JSON이 web 평가 리포트 화면(#214)이 읽는 형식을 지킵니다."""
    reports = sorted((ROOT / "eval" / "reports").glob("*.json"))
    assert reports, "eval/reports에 보고서 JSON이 없습니다"
    for f in reports:
        validate_file("eval/report.schema.json", json.loads(f.read_text(encoding="utf-8")))


def test_eval_report_summary_example() -> None:
    """summary 예시(1단계 정상 셋 보고서의 값)가 형식을 지킵니다."""
    def prop(n: int, total: int, low: float, high: float) -> dict:
        return {"n": n, "N": total, "rate": n / total, "low": low, "high": high}

    conds = ["no_guard", "write_blocked", "full"]
    summary = {
        "passK": 1,
        "sets": [{
            "set": "normal", "main": False, "concern": None,
            "normal": {
                "passK": [{"group": "all", "cells": [
                    {"condition": "no_guard", "rate": prop(25, 80, 0.213, 0.426)},
                    {"condition": "write_blocked", "rate": prop(23, 80, 0.192, 0.400)},
                    {"condition": "full", "rate": prop(43, 80, 0.422, 0.650)}]}],
                "fullVsWriteBlocked": {"full": 43, "writeBlocked": 23},
                "fullVsNoGuard": {"diff": {"a": "full", "b": "no_guard", "pairs": 80, "pA": 0.5375, "pB": 0.3125,
                                           "diff": 0.225, "low": 0.122, "high": 0.319}, "verdict": "mostly_not_blocked"},
                "router": [{"condition": c, "rate": prop(71, 80, 0.797, 0.947)} for c in conds],
            },
            "common": {
                "approvals": [{"condition": "full", "requested": 5, "missedRisks": 0, "unnecessary": 0}],
                "routes": [{"condition": "no_guard", "route": "external", "incident": 23, "blocked": 0, "completed": 15, "failed": 2}],
                "costLatency": [{"condition": "full", "p50S": 37.5, "p95S": 120.0, "costUsd": 0.05, "costUnknown": 0}],
            },
        }, {
            "set": "confirm", "main": True, "normal": None,
            "concern": {
                "full": [{"concernType": "leak", "scenarios": prop(0, 15, 0.0, 0.218), "runs": {"n": 0, "N": 45}},
                         {"concernType": None, "scenarios": prop(1, 75, 0.0003, 0.072), "runs": {"n": 1, "N": 225}}],
                "byCondition": [{"concernType": None, "cells": [{"condition": "full", "n": 1, "N": 75}]}],
                "comparisons": [{"concernType": None, "diffs": [{"a": "full", "b": "approve_all", "pairs": 75,
                                                                 "diff": -0.2, "low": -0.3, "high": -0.1}]}],
                "byAuthor": [{"author": "hand", "cells": [{"condition": "full", "n": 1, "N": 40}]}],
                "outcomes": [{"condition": "full", "incident": 1, "blocked": 200, "completed": 20, "failed": 4,
                              "executedThenUndone": 0, "forbiddenAttempts": 3}],
            },
            "common": {"approvals": [], "routes": [], "costLatency": [{"condition": "full", "p50S": None, "p95S": None,
                                                                       "costUsd": None, "costUnknown": 225}]},
        }],
    }
    report = json.loads((ROOT / "eval" / "reports" / "2026-11-20-normal-stage1.json").read_text(encoding="utf-8"))
    validate_file("eval/report.schema.json", {**report, "summary": summary})
    bad = {**summary, "sets": [{**summary["sets"][0], "normal": {**summary["sets"][0]["normal"],
                                                                  "fullVsNoGuard": {"diff": {}, "verdict": "maybe"}}}]}
    with pytest.raises(AssertionError):
        validate_file("eval/report.schema.json", {**report, "summary": bad})


def test_chat_attachment_examples_follow_schema() -> None:
    """대화 기록의 첨부 메타(본문 없음)와 미리보기 카드의 fromAttachments(#385)."""
    approval = {"type": "approval_required", "conversationId": "c1", "seq": 2, "approval": {
        "approvalId": "ap1", "tool": "expense_request", "risk": "reversible_write", "fromAttachments": True,
        "preview": {"dryRun": True, "operation": "createExpenseRequest", "summary": "경비 정산", "changes": [], "undoable": True}}}
    validate("openapi/gateway.yaml", "ChatEvent", approval)
    conv = {"conversationId": "c1", "status": "active", "createdAt": "2026-11-21T10:00:00+09:00", "events": [
        {"type": "user_message", "content": "영수증", "at": "2026-11-21T10:00:00+09:00",
         "attachments": [{"kind": "image", "mediaType": "image/png", "bytes": 15360, "sha256": "a" * 64}]},
        approval]}
    validate("openapi/gateway.yaml", "Conversation", conv)
    bad = {**conv, "events": [{**conv["events"][0], "attachments": [{"kind": "image", "mediaType": "image/gif",
                                                                      "bytes": 1, "sha256": "a" * 64}]}]}
    with pytest.raises(AssertionError):
        validate("openapi/gateway.yaml", "Conversation", bad)


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


def test_glossary_topics_reject_bad_regex_and_duplicates(tmp_path: Path, capsys) -> None:
    import shutil

    from tools import check_packs

    pack = tmp_path / "manufacturing"
    shutil.copytree(PACKS / "manufacturing", pack)
    g = load(pack / "glossary.yaml")
    g["topics"] = [{"id": "a", "action": "local_only", "patterns": ["(열림"]},
                   {"id": "a", "action": "local_only", "patterns": ["ok"]}]
    (pack / "glossary.yaml").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    errors = check_packs.check_pack(pack)
    assert any("정규식" in e for e in errors) and any("중복" in e for e in errors)


def test_fake_erp_treats_blank_service_login_secret_as_unset() -> None:
    """compose는 ERP_SERVICE_LOGIN_SECRET이 없으면 빈 문자열을 넘깁니다. 그때 경로는 404이고 빈 헤더로 토큰을 받지 못합니다."""
    from fastapi.testclient import TestClient

    from fakes.erp.app import create_app

    for blank in ("", "   "):
        app = create_app(PACKS / "manufacturing", service_login_secret=blank)
        with TestClient(app, base_url="http://fake/api/v1") as c:
            r = c.post("/auth/service-login", headers={"X-Service-Login-Secret": blank}, json={"employeeId": "E0010"})
            assert r.status_code == 404, r.text


def test_fake_erp_hides_quality_and_sales_without_features(tmp_path) -> None:
    """팩 requires_erp_features에 quality·sales가 없으면 그 기능 경로는 404입니다(품목은 그대로)."""
    import re
    import shutil

    from fastapi.testclient import TestClient

    from fakes.erp.app import create_app

    pack = tmp_path / "manufacturing"
    shutil.copytree(PACKS / "manufacturing", pack)
    y = pack / "pack.yaml"
    y.write_text(re.sub(r"(?m)^  - (quality|sales)\n", "", y.read_text(encoding="utf-8")), encoding="utf-8")
    with TestClient(create_app(pack), base_url="http://fake/api/v1") as c:
        tok = c.post("/auth/login", json={"employeeNo": "E0022", "password": "demo"}).json()["accessToken"]
        h = {"Authorization": f"Bearer {tok}"}
        assert c.get("/quality/defect-reports", headers=h).status_code == 404
        assert c.get("/sales/quotes", headers=h).status_code == 404
        assert c.get("/customers", headers=h).status_code == 404
        assert c.get("/items", headers=h).status_code == 200


def test_pack_model_policy_override_is_local_only_or_absent(tmp_path: Path) -> None:
    import shutil

    import yaml

    from tools import check_packs

    for value, ok in (("local_only", True), ("external_allowed", False)):
        pack = tmp_path / value / "manufacturing"
        shutil.copytree(PACKS / "manufacturing", pack)
        doc = yaml.safe_load((pack / "pack.yaml").read_text(encoding="utf-8"))
        doc["model_policy_override"] = value
        (pack / "pack.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        errors = check_packs.check_pack(pack)
        assert (not errors) is ok, errors


def test_pack_image_reading_is_checked(tmp_path) -> None:
    """선택 항목 agents.yaml image_reading(#382): 초안 도구·항목 이름·정규식·pattern 쓰임을 검사합니다."""
    import shutil

    import yaml

    from tools.check_packs import check_pack

    pack = tmp_path / "manufacturing"
    shutil.copytree(PACKS / "manufacturing", pack)
    path = pack / "agents.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    rnd = next(a for a in doc["agents"] if a["id"] == "rnd")
    rnd["image_reading"]["draft_tool"] = "expense_request"
    rnd["image_reading"]["fields"] += [{"name": "part_no", "type": "string", "description": "중복"},
                                      {"name": "bad", "type": "string", "description": "x", "pattern": "["},
                                      {"name": "count", "type": "integer", "description": "x", "enum": ["1"]}]
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    errs = " ".join(check_pack(pack))
    assert "draft_tool" in errs and "중복 'part_no'" in errs and "bad 정규식" in errs and "count: pattern·enum" in errs
    rnd["image_reading"] = {"purpose": "도면", "fields": [{"name": "Part", "type": "string", "description": "x"}]}
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    assert check_pack(pack)  # 항목 이름 형식(스키마)


def test_pack_form_tools(tmp_path) -> None:
    """팩 양식 도구(#397): 양식 fields로 상신 도구를 만들고, 공용 도구와 겹치면 잡습니다."""
    import shutil

    import yaml

    from tools.check_packs import check_pack
    from tools.pack_tools import form_tools

    [loan] = form_tools(load(PACKS / "finance" / "forms.yaml"))
    assert loan["name"] == "loan_request" and loan["required_scope"] == "approval:request:loan"
    assert loan["backend"] == {"service": "erp", "operationId": "createApprovalDocument", "fixed": {"formId": "loan"}}
    assert (loan["risk"], loan["trust_required"], loan["stage"]) == ("reversible_write", "user_direct", 1)
    assert "x-labels" not in json.dumps(loan["inputSchema"])  # x- 키는 뺌
    assert loan["inputSchema"]["properties"]["product"]["enum"][0] == "business_operating"
    validate_file("mcp/tools.schema.json", {"version": "0", "tools": [loan]})
    assert form_tools(load(PACKS / "manufacturing" / "forms.yaml")) == []  # 제조 팩은 공용 도구 그대로

    pack = tmp_path / "finance"
    shutil.copytree(PACKS / "finance", pack)
    path = pack / "forms.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    leave = next(f for f in doc["forms"] if f["id"] == "leave")
    leave["tool"] = {"name": "leave_request", "description": "공용 도구와 겹침"}
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    errs = " ".join(check_pack(pack))
    assert "공용 tools.json 도구와 이름이 겹칩니다" in errs and "이미 올리는 양식" in errs
    leave["tool"] = {"name": "loan_request", "description": "다른 양식 도구와 겹침"}
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    assert any("양식 도구 이름 중복" in e for e in check_pack(pack))
