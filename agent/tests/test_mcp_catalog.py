"""도구 목록이 계약 그대로인지, 결재 승인 도구가 없는지, 인자를 요청에 바르게 놓는지 봅니다."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
import yaml

from agent_runtime.mcp_server.catalog import Catalog, CatalogError, build_request
from agent_runtime.mcp_server.server import tool_descriptor
from agent_runtime.registry import Registry
from tests.conftest import CONTRACTS, PACK_DIR

TOOLS_JSON = json.loads((CONTRACTS / "mcp" / "tools.json").read_text("utf-8"))
SNAPSHOT = Path(__file__).parent / "snapshots" / "mcp_tools_list.json"


@pytest.fixture(scope="module")
def catalog(registry: Registry) -> Catalog:
    return Catalog.load(CONTRACTS / "mcp" / "tools.json", CONTRACTS / "openapi", registry)


def _listing(catalog: Catalog) -> list[dict]:
    return [tool_descriptor(t).model_dump(by_alias=True, exclude_none=True, mode="json") for t in catalog.tools]


def test_exposed_tools_are_those_of_enabled_agents(catalog: Catalog, registry: Registry) -> None:
    assert {t.name for t in catalog.tools} == {n for a in registry.agents for n in a.tools}


def test_name_description_schema_are_verbatim_from_contract(catalog: Catalog) -> None:
    by_name = {t["name"]: t for t in TOOLS_JSON["tools"]}
    for d in _listing(catalog):
        src = by_name[d["name"]]
        assert d["description"] == src["description"]
        assert d["inputSchema"] == src["inputSchema"]
        assert d["_meta"]["risk"] == src["risk"]
        assert d["_meta"]["trustRequired"] == src["trust_required"]
        assert d["annotations"]["readOnlyHint"] is (src["risk"] == "read")
        assert d["annotations"]["destructiveHint"] is (src["risk"] == "irreversible")


def test_tools_list_snapshot(catalog: Catalog) -> None:
    """tools/list 응답 전체의 스냅숏. 의도한 변경이면 UPDATE_SNAPSHOTS=1로 다시 만듭니다."""
    current = _listing(catalog)
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", "utf-8")
    assert SNAPSHOT.exists(), "스냅숏이 없습니다. UPDATE_SNAPSHOTS=1로 만듭니다"
    assert current == json.loads(SNAPSHOT.read_text("utf-8"))


# ---- 결재 승인 도구 없음 ----


def _human_only_or_decide_ops() -> set[str]:
    spec = yaml.safe_load((CONTRACTS / "openapi" / "erp.yaml").read_text("utf-8"))
    out = set()
    for item in spec["paths"].values():
        for op in item.values():
            if isinstance(op, dict) and (op.get("x-human-only") or op.get("x-required-scope") == "approval:decide"):
                out.add(op["operationId"])
    return out


def test_no_approval_decision_tool_is_exposed(catalog: Catalog) -> None:
    forbidden = _human_only_or_decide_ops()
    assert {"approveApprovalDocument", "rejectApprovalDocument"} <= forbidden
    for t in catalog.tools:
        assert t.operation.operation_id not in forbidden
        assert t.required_scope != "approval:decide"
        assert "approve" not in t.name and "reject" not in t.name


def test_contract_tool_list_has_no_approval_decision_tool() -> None:
    forbidden = _human_only_or_decide_ops()
    assert all(t["backend"]["operationId"] not in forbidden for t in TOOLS_JSON["tools"])


def test_catalog_refuses_human_only_operation(tmp_path: Path, registry: Registry) -> None:
    doc = json.loads(json.dumps(TOOLS_JSON))
    tool = next(t for t in doc["tools"] if t["name"] == "approval_get")
    tool["backend"]["operationId"] = "approveApprovalDocument"
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(doc), "utf-8")
    with pytest.raises(CatalogError, match="사람 화면 전용"):
        Catalog.load(path, CONTRACTS / "openapi", registry)


def test_catalog_refuses_registry_tool_missing_from_contract(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(PACK_DIR, pack)
    agents = yaml.safe_load((pack / "agents.yaml").read_text("utf-8"))
    agents["agents"][0]["tools"].append("ghost_tool")
    (pack / "agents.yaml").write_text(yaml.safe_dump(agents, allow_unicode=True), "utf-8")
    with pytest.raises(CatalogError, match="ghost_tool"):
        Catalog.load(CONTRACTS / "mcp" / "tools.json", CONTRACTS / "openapi", Registry.load(pack))


# ---- 인자 배치 ----


@pytest.mark.parametrize(
    ("tool", "args", "expected"),
    [
        ("leave_request", {"leave_type": "annual", "start_date": "2027-01-04", "end_date": "2027-01-04", "reason": "r"},
         ("post", "/api/v1/approval-documents", {},
          {"formId": "leave", "fields": {"leave_type": "annual", "start_date": "2027-01-04",
                                         "end_date": "2027-01-04", "reason": "r"}})),
        ("approval_list_mine", {"status": "approved"},
         ("get", "/api/v1/approval-documents", {"box": "outbox", "status": "approved"}, None)),
        ("approval_withdraw", {"documentId": "D1", "reason": "r"},
         ("post", "/api/v1/approval-documents/D1/withdraw", {}, {"reason": "r"})),
        ("delegation_register", {"delegateId": "E2", "startsAt": "s", "endsAt": "e", "formTypes": ["leave"],
                                 "maxAmount": 100, "reason": "r"},
         ("post", "/api/v1/delegations", {},
          {"delegateId": "E2", "startsAt": "s", "endsAt": "e", "reason": "r",
           "scope": {"formTypes": ["leave"], "maxAmount": 100}})),
        ("room_list_my_reservations", {"date": "2027-01-04"},
         ("get", "/api/v1/room-reservations", {"mine": "true", "date": "2027-01-04"}, None)),
        ("room_cancel_reservation", {"reservationId": "R1"},
         ("post", "/api/v1/room-reservations/R1/cancel", {}, {})),
        ("policy_search", {"question": "q"}, ("post", "/answer", {}, {"question": "q"})),
    ],
)
def test_build_request(catalog: Catalog, tool: str, args: dict, expected: tuple) -> None:
    r = build_request(catalog.get(tool), args)
    assert (r.method, r.path, r.query, r.body) == expected


@pytest.mark.parametrize("bad", ["", "..", "."])
def test_build_request_rejects_bad_path_values(catalog: Catalog, bad: str) -> None:
    with pytest.raises(CatalogError):
        build_request(catalog.get("approval_get"), {"documentId": bad})


@pytest.mark.parametrize(
    ("value", "path"),
    [
        ("D1#", "/api/v1/approval-documents/D1%23/withdraw"),
        ("D1?x=1", "/api/v1/approval-documents/D1%3Fx%3D1/withdraw"),
        ("a/b", "/api/v1/approval-documents/a%2Fb/withdraw"),
        ("%2e%2e", "/api/v1/approval-documents/%252e%252e/withdraw"),
        ("X\n", "/api/v1/approval-documents/X%0A/withdraw"),
    ],
)
def test_path_values_are_percent_encoded(catalog: Catalog, value: str, path: str) -> None:
    assert build_request(catalog.get("approval_withdraw"), {"documentId": value}).path == path


def test_fixed_value_wins_over_argument(catalog: Catalog) -> None:
    r = build_request(catalog.get("approval_list_mine"), {"box": "inbox"})
    assert r.query["box"] == "outbox"
    r = build_request(catalog.get("room_list_my_reservations"), {"mine": False})
    assert r.query["mine"] == "true"


def _write_tools(tmp_path: Path, edit) -> Path:
    doc = json.loads(json.dumps(TOOLS_JSON))
    edit(doc)
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(doc), "utf-8")
    return path


def test_catalog_refuses_fixed_name_in_input_schema(tmp_path: Path, registry: Registry) -> None:
    def add_box(doc):
        t = next(t for t in doc["tools"] if t["name"] == "approval_list_mine")
        t["inputSchema"]["properties"]["box"] = {"type": "string"}

    with pytest.raises(CatalogError, match="고정값"):
        Catalog.load(_write_tools(tmp_path, add_box), CONTRACTS / "openapi", registry)


def test_catalog_refuses_later_stage_tool_in_registry(tmp_path: Path, registry: Registry) -> None:
    def stage2(doc):
        next(t for t in doc["tools"] if t["name"] == "room_reserve")["stage"] = 2

    with pytest.raises(CatalogError, match="단계 2"):
        Catalog.load(_write_tools(tmp_path, stage2), CONTRACTS / "openapi", registry)


def test_later_stage_tool_not_in_registry_is_hidden(tmp_path: Path, registry: Registry) -> None:
    def add_stage2(doc):
        extra = dict(next(t for t in doc["tools"] if t["name"] == "approval_get"), name="later_tool", stage=2)
        doc["tools"].append(extra)

    cat = Catalog.load(_write_tools(tmp_path, add_stage2), CONTRACTS / "openapi", registry)
    assert cat.get("later_tool") is None
