"""평가 보고서 조회 `/api/eval/reports`(#332, 계약 #334)."""

import dataclasses
import json
import shutil

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app

from .conftest import ROOT, _employees
from .test_chat import schema_check

REAL = ROOT / "eval/reports/2026-11-20-normal-stage1.json"


def _meta(started, **kw):
    return {"commit": "abc", "dirty": False, "machine": "m", "started_at": started, "finished_at": None,
            "conditions": ["full"], "repeats": 1, "planned_runs": 2, "done_runs": 1, "complete": False, **kw}


@pytest.fixture
def reports(tmp_path):
    d = tmp_path / "reports"
    d.mkdir()
    shutil.copy(REAL, d / REAL.name)
    shutil.copy(REAL.with_suffix(".md"), d / REAL.with_suffix(".md").name)
    (d / "2026-11-21-confirm.json").write_text(json.dumps({
        "meta": _meta("2026-11-21T09:00:00+09:00", pack_stage=2),
        "rows": [{"set": "confirm"}, {"set": "normal"}, {"set": "confirm"}],
        "summary": {"x": 1}}), encoding="utf-8")
    (d / "broken.json").write_text("{", encoding="utf-8")                 # 읽지 못하는 파일은 건너뜀
    (d / "2026-11-21-confirm.rows.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "secret.json").write_text(json.dumps({"meta": _meta("2026-01-01T00:00:00+09:00"), "rows": []}))
    return d


@pytest.fixture
def rc(settings, fake_erp, issuer, reports):
    app = create_app(dataclasses.replace(settings, eval_reports_dir=reports),
                     erp_transport=httpx.ASGITransport(app=fake_erp), issuer=issuer)
    with TestClient(app) as c:
        yield c


def _h(c, grade_or_unit):
    emp = next(e for e in _employees() if e["unit_id"] == grade_or_unit or e["grade"] == grade_or_unit)
    tok = c.post("/api/auth/login", json={"employeeNo": emp["employee_no"], "password": "demo-pass"}).json()
    return {"Authorization": f"Bearer {tok['accessToken']}"}


def test_list_newest_first_with_title_sets_and_summary_flag(rc):
    r = rc.get("/api/eval/reports", headers=_h(rc, "it-ops"))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    for it in items:
        schema_check.validate("openapi/gateway.yaml", "EvalReportSummary", it)
    assert [i["reportId"] for i in items] == ["2026-11-21-confirm", "2026-11-20-normal-stage1"]
    new, old = items
    assert new["title"] is None and new["sets"] == ["confirm", "normal"] and new["hasSummary"] is True
    assert new["packStage"] == 2 and new["doneRuns"] == 1 and new["plannedRuns"] == 2 and new["complete"] is False
    real = json.loads(REAL.read_text(encoding="utf-8"))
    assert old["title"] == REAL.with_suffix(".md").read_text(encoding="utf-8").splitlines()[0].removeprefix("# ")
    assert old["hasSummary"] is ("summary" in real) and old["startedAt"] == real["meta"]["started_at"]


def test_get_returns_report_json_as_is(rc):
    r = rc.get("/api/eval/reports/2026-11-20-normal-stage1", headers=_h(rc, "it-ops"))
    assert r.status_code == 200
    assert r.json() == json.loads(REAL.read_text(encoding="utf-8"))


@pytest.mark.parametrize("rid", ["nope", "secret", "..", "...json", ".hidden", "a b", "2026-11-21-confirm.rows",
                                 "broken"])
def test_unknown_outside_or_bad_ids_are_404(rc, rid):
    r = rc.get(f"/api/eval/reports/{rid}", headers=_h(rc, "it-ops"))
    assert r.status_code == 404, (rid, r.text)


@pytest.mark.parametrize("path", ["/api/eval/reports/..%2Fsecret", "/api/eval/reports/%2e%2e%2fsecret"])
def test_encoded_traversal_is_not_served(rc, path):
    r = rc.get(path, headers=_h(rc, "it-ops"))
    assert r.status_code == 404 and "2026-01-01" not in r.text


def test_symlink_out_of_folder_is_404(rc, reports):
    (reports / "link.json").symlink_to(reports.parent / "secret.json")
    h = _h(rc, "it-ops")
    assert rc.get("/api/eval/reports/link", headers=h).status_code == 404
    assert "link" not in [i["reportId"] for i in rc.get("/api/eval/reports", headers=h).json()["items"]]


def test_auditor_only(rc):
    h = _h(rc, "staff")
    assert rc.get("/api/eval/reports", headers=h).status_code == 403
    assert rc.get("/api/eval/reports/2026-11-20-normal-stage1", headers=h).status_code == 403
    assert rc.get("/api/eval/reports").status_code == 401


def test_missing_folder_is_empty_list(settings, fake_erp, issuer, tmp_path):
    app = create_app(dataclasses.replace(settings, eval_reports_dir=tmp_path / "none"),
                     erp_transport=httpx.ASGITransport(app=fake_erp), issuer=issuer)
    with TestClient(app) as c:
        assert c.get("/api/eval/reports", headers=_h(c, "it-ops")).json() == {"items": []}


def test_settings_read_reports_dir(monkeypatch, tmp_path):
    from gateway.config import Settings

    monkeypatch.setenv("GATEWAY_EVAL_REPORTS_DIR", str(tmp_path))
    assert Settings.from_env().eval_reports_dir == tmp_path
    monkeypatch.delenv("GATEWAY_EVAL_REPORTS_DIR")
    assert Settings.from_env().eval_reports_dir == ROOT / "eval/reports"
