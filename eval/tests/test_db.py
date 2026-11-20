import pytest

from harness.db import check_db, evaluate


@pytest.mark.parametrize("op, matches, value, ok", [
    ("equals", ["a", "a"], "a", True),
    ("equals", [], "a", False),
    ("equals", ["a", "b"], "a", False),
    ("not_equals", [], "a", True),
    ("not_equals", ["b"], "a", True),
    ("not_equals", ["a"], "a", False),
    ("exists", [0], None, True),
    ("exists", [], None, False),
    ("not_exists", [], None, True),
    ("count_equals", [1, 2], 2, True),
    ("count_equals", [1], 2, False),
    ("count_gte", [1, 2, 3], 2, True),
    ("count_gte", [1], 2, False),
])
def test_evaluate(op, matches, value, ok):
    assert evaluate(op, matches, value) is ok


def test_check_db_against_fake_erp(erp):
    res = erp.call_ok("E0016", "createApprovalDocument", body={"formId": "leave", "fields": {
        "leave_type": "half_pm", "start_date": "2027-03-02", "end_date": "2027-03-02", "reason": "병원"}})
    doc = res["resource"]["id"]
    results = check_db([
        {"as": "E0016", "operation": "getApprovalDocument", "params": {"documentId": "${doc}"},
         "jsonPath": "$.status", "op": "equals", "value": "in_progress"},
        {"as": "E0016", "operation": "listApprovalDocuments", "params": {"box": "outbox"},
         "jsonPath": "$.items[?(@.fields.leave_type == 'half_pm')]", "op": "count_equals", "value": 1},
        {"as": "E0016", "operation": "getApprovalDocument", "params": {"documentId": "nope"},
         "jsonPath": "$.id", "op": "not_exists"},
        {"as": "E0016", "operation": "getApprovalDocument", "params": {"documentId": "nope"},
         "jsonPath": "$.id", "op": "exists"},
    ], erp, {"doc": doc})
    assert [r.ok for r in results] == [True, True, True, False]
    assert "조회 실패 404" in results[3].detail


def test_reset_restores_pack_state(monkeypatch):
    from harness.erp import ErpCallError, ErpClient
    from tests.conftest import PASSWORD, new_fake_erp

    monkeypatch.setenv("ERP_EVAL_RESET", "1")
    with new_fake_erp() as c:
        erp = ErpClient(c, password=PASSWORD)
        erp.call_ok("E0016", "createApprovalDocument", body={"formId": "leave", "fields": {
            "leave_type": "annual", "start_date": "2027-03-02", "end_date": "2027-03-02", "reason": "x"}})
        erp.reset()
        assert erp.call_ok("E0016", "listApprovalDocuments", {"box": "outbox"})["items"] == []
    monkeypatch.delenv("ERP_EVAL_RESET")
    with new_fake_erp() as c:
        with pytest.raises(ErpCallError, match="ERP_EVAL_RESET"):
            ErpClient(c, password=PASSWORD).reset()
