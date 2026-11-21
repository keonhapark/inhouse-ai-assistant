"""슬랙 브리지 로그인 `POST /api/auth/slack`(#273, 계약 #297, erp 서비스 로그인 #316)."""

import dataclasses
import json
import secrets

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app

from .conftest import PACK, PASSWORD, _employees, create_fake_erp
from .test_chat import schema_check

BRIDGE = secrets.token_hex(16)
SERVICE = secrets.token_hex(16)


@pytest.fixture
def emp():
    return next(e for e in _employees() if e["grade"] == "staff")


@pytest.fixture
def auditor():
    return next(e for e in _employees() if e["unit_id"] == "it-ops")


@pytest.fixture
def users_file(tmp_path, emp, auditor):
    p = tmp_path / "slack-users.json"
    p.write_text(json.dumps({"_설명": "시험", "users": {"U1": emp["id"], "U2": auditor["id"], "U9": "E9999"}}),
                 encoding="utf-8")
    return p


def _app(settings, issuer, users_file, *, bridge=BRIDGE, service=SERVICE, erp_service=SERVICE):
    erp = create_fake_erp(PACK, demo_password=PASSWORD, delegation_public_key=issuer.public_pem(),
                          service_login_secret=erp_service)
    s = dataclasses.replace(settings, slack_bridge_secret=bridge, slack_users_file=users_file,
                            erp_service_login_secret=service)
    return create_app(s, erp_transport=httpx.ASGITransport(app=erp), issuer=issuer)


@pytest.fixture
def sc(settings, issuer, users_file):
    app = _app(settings, issuer, users_file)
    with TestClient(app) as c:
        c.app_ref = app
        yield c


def _login(c, slack_id="U1", secret=BRIDGE):
    return c.post("/api/auth/slack", headers={"X-Slack-Bridge-Secret": secret}, json={"slackUserId": slack_id})


def _audit(c):
    return [e for e in c.app_ref.state.audit.events.read_all() if e["kind"] == "auth.login"]


def test_mapped_user_gets_short_employee_jwt_with_slack_amr(sc, emp):
    r = _login(sc)
    assert r.status_code == 200, r.text
    body = r.json()
    schema_check.validate("openapi/erp.yaml", "LoginResponse", body)
    claims = jwt.decode(body["accessToken"], options={"verify_signature": False})
    assert claims["sub"] == emp["id"] and "slack" in claims["amr"]
    # 그 토큰으로 일반 기능은 됩니다
    h = {"Authorization": f"Bearer {body['accessToken']}"}
    assert sc.get("/api/me", headers=h).json()["id"] == emp["id"]
    assert sc.post("/api/conversations", headers=h, json={}).status_code == 201
    (ev,) = _audit(sc)
    assert ev["result"] == "ok" and ev["actor"]["employeeId"] == emp["id"] and "slack" in ev["detail"]
    assert body["accessToken"] not in json.dumps(_audit(sc)) and BRIDGE not in json.dumps(_audit(sc))


@pytest.mark.parametrize("secret", ["", "wrong", BRIDGE + "x"])
def test_wrong_or_missing_bridge_secret_is_401(sc, secret):
    r = _login(sc, secret=secret)
    assert r.status_code == 401 and r.json()["type"] == "urn:problem:unauthorized"
    assert _audit(sc)[-1]["result"] == "denied"


def test_missing_header_is_401(sc):
    assert sc.post("/api/auth/slack", json={"slackUserId": "U1"}).status_code == 401


@pytest.mark.parametrize("slack_id", ["U404", "U9"])  # 매핑에 없음, 매핑된 직원이 erp에 없음
def test_unmapped_or_unknown_employee_is_403(sc, slack_id):
    r = _login(sc, slack_id)
    assert r.status_code == 403 and r.json()["type"] == "urn:problem:forbidden"
    ev = _audit(sc)[-1]
    assert ev["result"] == "denied" and ev["actor"]["employeeId"] is None


@pytest.mark.parametrize("body", [{}, {"slackUserId": 1}, {"slackUserId": "U1", "x": 1}, ["U1"]])
def test_bad_body_is_422(sc, body):
    r = sc.post("/api/auth/slack", headers={"X-Slack-Bridge-Secret": BRIDGE}, json=body)
    assert r.status_code == 422


def test_route_is_404_without_bridge_secret(settings, issuer, users_file):
    with TestClient(_app(settings, issuer, users_file, bridge=None)) as c:
        assert _login(c, secret="anything").status_code == 404


def test_missing_mapping_file_means_nobody_is_mapped(settings, issuer, tmp_path):
    with TestClient(_app(settings, issuer, tmp_path / "none.json")) as c:
        assert _login(c).status_code == 403


def test_erp_rejecting_service_secret_is_502_not_401(settings, issuer, users_file):
    """gateway 설정 문제(erp 서비스 비밀값 불일치)를 브리지 인증 실패로 보이지 않게 합니다."""
    with TestClient(_app(settings, issuer, users_file, service="mismatch")) as c:
        r = _login(c)
        assert r.status_code == 502 and SERVICE not in r.text


def test_slack_token_cannot_use_human_only_routes(sc, auditor):
    """감사·운영 조회는 사람 화면 전용입니다. auditor 직원이라도 슬랙 토큰이면 403입니다."""
    tok = _login(sc, "U2").json()["accessToken"]
    h = {"Authorization": f"Bearer {tok}"}
    for path in ("/api/audit-events", "/api/ops/metrics", "/api/ops/egress"):
        r = sc.get(path, headers=h)
        assert r.status_code == 403 and r.json()["type"] == "urn:problem:service-login-not-allowed", (path, r.text)
    # 같은 직원의 비밀번호 로그인 토큰은 됩니다
    pw = sc.post("/api/auth/login", json={"employeeNo": auditor["employee_no"], "password": PASSWORD}).json()
    assert sc.get("/api/audit-events", headers={"Authorization": f"Bearer {pw['accessToken']}"}).status_code == 200


def test_settings_read_slack_env(monkeypatch, tmp_path):
    from gateway.config import Settings

    monkeypatch.setenv("SLACK_BRIDGE_SECRET", "b")
    monkeypatch.setenv("SLACK_USERS_FILE", str(tmp_path / "u.json"))
    monkeypatch.setenv("ERP_SERVICE_LOGIN_SECRET", "s")
    s = Settings.from_env()
    assert (s.slack_bridge_secret, s.slack_users_file, s.erp_service_login_secret) == ("b", tmp_path / "u.json", "s")
    monkeypatch.setenv("SLACK_BRIDGE_SECRET", "")
    assert Settings.from_env().slack_bridge_secret is None


@pytest.mark.parametrize("service", [None, ""])
def test_missing_service_secret_never_calls_erp(settings, issuer, users_file, service):
    calls = []
    erp = create_fake_erp(PACK, demo_password=PASSWORD, delegation_public_key=issuer.public_pem(),
                          service_login_secret=SERVICE)

    async def spy(scope, receive, send):
        calls.append(scope["path"])
        await erp(scope, receive, send)
    s = dataclasses.replace(settings, slack_bridge_secret=BRIDGE, slack_users_file=users_file,
                            erp_service_login_secret=service)
    with TestClient(create_app(s, erp_transport=httpx.ASGITransport(app=spy), issuer=issuer)) as c:
        assert _login(c).status_code == 502
    assert not any(p.endswith("/auth/service-login") for p in calls)


@pytest.mark.parametrize("amr", ["slack", ["pwd", "slack"]])
def test_reject_service_login_handles_string_and_list_amr(amr):
    from gateway.problems import ProblemError
    from gateway.slack_login import reject_service_login

    tok = jwt.encode({"sub": "E1", "amr": amr}, "k" * 32, algorithm="HS256")
    with pytest.raises(ProblemError) as e:
        reject_service_login(tok)
    assert e.value.status == 403
    reject_service_login(jwt.encode({"sub": "E1", "amr": ["pwd"]}, "k" * 32, algorithm="HS256"))
