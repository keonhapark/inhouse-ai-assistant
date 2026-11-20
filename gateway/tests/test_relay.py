"""사람 화면 경로(결재함·대결·되돌리기·알림)를 가짜 erp에 중계하는지 봅니다."""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import yaml

from .conftest import PACK, _employees

KST = ZoneInfo("Asia/Seoul")


@pytest.fixture(scope="module")
def team():
    by_unit = defaultdict(list)
    for e in _employees():
        by_unit[e["unit_id"]].append(e)
    for unit, emps in by_unit.items():
        leaders = [e for e in emps if e["grade"] == "team_leader"]
        staff = [e for e in emps if e["grade"] == "staff"]
        if leaders and len(staff) >= 2 and unit != "hr":
            return {"leader": leaders[0], "requester": staff[0], "deputy": staff[1]}
    raise AssertionError("팀장과 팀원 둘이 있는 팀이 없습니다")


@pytest.fixture
def auth(login):
    cache = {}

    def _auth(emp: dict) -> dict:
        if emp["id"] not in cache:
            cache[emp["id"]] = {"Authorization": f"Bearer {login(emp['employee_no'])}"}
        return cache[emp["id"]]
    return _auth


def _key() -> dict:
    return {"Idempotency-Key": uuid.uuid4().hex}


_day = [0]


def _weekday() -> str:
    _day[0] += 1
    d = datetime.now(KST).date() + timedelta(days=30 + _day[0])
    while d.weekday() >= 5:
        d += timedelta(days=1)
        _day[0] += 1
    return d.isoformat()


def _request_leave(erp_http, auth, emp) -> dict:
    day = _weekday()
    r = erp_http.post("/approval-documents", headers={**auth(emp), **_key()}, json={
        "formId": "leave", "fields": {"leave_type": "annual", "start_date": day, "end_date": day, "reason": "개인 사정"}})
    assert r.status_code == 201, r.text
    return r.json()


def _delegate(client, auth, team, dry_run=False):
    start = datetime.now(KST) - timedelta(minutes=1)
    body = {"delegateId": team["deputy"]["id"], "startsAt": start.isoformat(),
            "endsAt": (start + timedelta(days=2)).isoformat(),
            "scope": {"formTypes": ["leave"], "maxAmount": None}, "reason": "출장"}
    url = "/api/delegations" + ("?dryRun=true" if dry_run else "")
    return client.post(url, headers={**auth(team["leader"]), **({} if dry_run else _key())}, json=body)


def test_inbox_adds_names(client, erp_http, auth, team):
    doc = _request_leave(erp_http, auth, team["requester"])["resource"]
    r = client.get("/api/inbox?box=inbox", headers=auth(team["leader"]))
    assert r.status_code == 200
    item = next(i for i in r.json()["items"] if i["id"] == doc["id"])
    assert item["requesterName"] == team["requester"]["name"]
    forms = yaml.safe_load((PACK / "forms.yaml").read_text(encoding="utf-8"))
    forms = forms["forms"] if isinstance(forms, dict) else forms
    assert item["formName"] == next(f["name"] for f in forms if f["id"] == "leave")
    assert item["viaDelegation"] is None


def test_delegation_flow_through_gateway(client, erp_http, auth, team):
    preview = _delegate(client, auth, team, dry_run=True)
    assert preview.status_code == 200 and preview.json()["dryRun"] is True
    created = _delegate(client, auth, team)
    assert created.status_code == 201, created.text
    dl_id = created.json()["resource"]["id"]

    views = client.get("/api/delegations?role=delegator", headers=auth(team["leader"])).json()["items"]
    v = next(d for d in views if d["id"] == dl_id)
    assert v["delegatorName"] == team["leader"]["name"] and v["delegateName"] == team["deputy"]["name"]

    doc = _request_leave(erp_http, auth, team["requester"])["resource"]
    box = client.get("/api/inbox?box=delegated", headers=auth(team["deputy"])).json()["items"]
    item = next(i for i in box if i["id"] == doc["id"])
    assert item["viaDelegation"]["delegationId"] == dl_id
    assert item["viaDelegation"]["originalApproverName"] == team["leader"]["name"]

    r = client.post(f"/api/inbox/{doc['id']}/approve", headers={**auth(team["deputy"]), **_key()},
                    json={"version": item["version"]})
    assert r.status_code == 201, r.text
    done = client.get(f"/api/inbox/{doc['id']}", headers=auth(team["deputy"])).json()
    assert done["viaDelegation"]["originalApproverId"] == team["leader"]["id"]

    r = client.post(f"/api/delegations/{dl_id}/revoke", headers={**auth(team["leader"]), **_key()})
    assert r.status_code == 201, r.text
    assert client.get("/api/notifications", headers=auth(team["leader"])).status_code == 200


def test_stale_version_conflict_is_relayed(client, erp_http, auth, team):
    doc = _request_leave(erp_http, auth, team["requester"])["resource"]
    r = client.post(f"/api/inbox/{doc['id']}/approve", headers={**auth(team["leader"]), **_key()},
                    json={"version": doc["version"] + 5})
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")


def test_reject(client, erp_http, auth, team):
    doc = _request_leave(erp_http, auth, team["requester"])["resource"]
    r = client.post(f"/api/inbox/{doc['id']}/reject", headers={**auth(team["leader"]), **_key()},
                    json={"version": doc["version"], "comment": "일정 조정"})
    assert r.status_code == 201, r.text


def test_undo_and_idempotency_key_are_relayed(client, erp_http, auth, team):
    action = _request_leave(erp_http, auth, team["requester"])
    key = _key()
    r1 = client.post(f"/api/actions/{action['actionId']}/undo", headers={**auth(team["requester"]), **key})
    assert r1.status_code == 201, r1.text
    r2 = client.post(f"/api/actions/{action['actionId']}/undo", headers={**auth(team["requester"]), **key})
    assert r2.status_code == 201 and r2.json() == r1.json()   # 같은 키는 처음 응답 그대로
    r3 = client.post(f"/api/actions/{action['actionId']}/undo", headers={**auth(team["requester"]), **_key()})
    assert r3.status_code == 409                                 # 이미 되돌림


def test_missing_idempotency_key_is_erp_400(client, auth, team):
    r = client.post("/api/delegations", headers=auth(team["leader"]), json={
        "delegateId": team["deputy"]["id"], "startsAt": "2026-12-01T09:00:00+09:00",
        "endsAt": "2026-12-02T09:00:00+09:00", "scope": {"formTypes": ["leave"]}, "reason": "출장"})
    assert r.status_code == 400 and r.json()["type"] == "urn:problem:idempotency-key-required"


def test_screen_routes_need_login(client):
    for method, path in [("GET", "/api/inbox?box=inbox"), ("GET", "/api/delegations?role=delegator"),
                         ("GET", "/api/notifications"), ("POST", "/api/actions/x/undo")]:
        r = client.request(method, path)
        assert r.status_code == 401, path
