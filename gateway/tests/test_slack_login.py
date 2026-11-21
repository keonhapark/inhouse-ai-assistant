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


def _app(settings, issuer, users_file, *, bridge=BRIDGE, service=SERVICE, erp_service=SERVICE, agent_transport=None):
    erp = create_fake_erp(PACK, demo_password=PASSWORD, delegation_public_key=issuer.public_pem(),
                          service_login_secret=erp_service)
    s = dataclasses.replace(settings, slack_bridge_secret=bridge, slack_users_file=users_file,
                            erp_service_login_secret=service)
    return create_app(s, erp_transport=httpx.ASGITransport(app=erp), issuer=issuer, agent_transport=agent_transport)


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
    """감사·운영 조회는 허용 목록 밖입니다. auditor 직원이라도 슬랙 토큰이면 403입니다."""
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
def test_string_and_list_amr_are_both_slack_tokens(amr):
    from gateway.slack_login import is_service_login_token

    assert is_service_login_token(jwt.encode({"sub": "E1", "amr": amr}, "k" * 32, algorithm="HS256"))
    assert not is_service_login_token(jwt.encode({"sub": "E1", "amr": ["pwd"]}, "k" * 32, algorithm="HS256"))
    assert not is_service_login_token("not-a-jwt")


ALLOWED = [("GET", "/api/me", None), ("GET", "/api/notifications", None), ("GET", "/api/conversations", None),
           ("POST", "/api/conversations", {}), ("GET", "/api/conversations/conv_x", None),
           ("POST", "/api/conversations/conv_x/messages", {"content": "hi"}),
           ("POST", "/api/execution-approvals/ap_x", {"decision": "approve"}), ("POST", "/api/actions/a_x/undo", None)]
DENIED = [("GET", "/api/agents", None), ("GET", "/api/agent-registry", None), ("GET", "/api/org/units", None),
          ("GET", "/api/employees", None), ("GET", "/api/approval-forms", None),
          ("GET", "/api/inbox?box=inbox", None), ("POST", "/api/inbox/d_x/approve", {"version": 1}),
          ("POST", "/api/inbox/d_x/reject", {"version": 1}), ("GET", "/api/delegations?role=delegator", None),
          ("POST", "/api/delegations", {}), ("POST", "/api/delegations/dl_x/revoke", None),
          ("GET", "/api/audit-events", None), ("GET", "/api/ops/metrics", None), ("GET", "/api/ops/egress", None),
          ("DELETE", "/api/conversations/conv_x", None)]


@pytest.mark.parametrize("method,path,body", DENIED)
def test_slack_token_is_refused_outside_allow_list(sc, method, path, body):
    """허용 목록 밖은 403입니다. 대결 등록으로 승인 권한을 넘기는 우회도 여기서 막힙니다(리드 결정)."""
    tok = _login(sc, "U2").json()["accessToken"]
    r = sc.request(method, path, headers={"Authorization": f"Bearer {tok}"}, json=body)
    if method == "DELETE":  # 없는 경로는 라우팅에서 405
        assert r.status_code in (403, 405)
        return
    assert r.status_code == 403 and r.json()["type"] == "urn:problem:service-login-not-allowed", (path, r.text)


@pytest.mark.parametrize("method,path,body", ALLOWED)
def test_slack_token_passes_allow_list(sc, method, path, body):
    tok = _login(sc).json()["accessToken"]
    r = sc.request(method, path, headers={"Authorization": f"Bearer {tok}"}, json=body)
    assert not (r.status_code == 403 and "service-login-not-allowed" in r.text), (path, r.text)


# ---------- 요청 횟수 제한(#331) ----------
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_rate_limiter_window_and_retry_after():
    from gateway.slack_login import RateLimiter

    clock = Clock()
    rl = RateLimiter(2, 60, clock=clock)
    assert rl.hit("a") is None and rl.hit("a") is None
    assert rl.hit("a") == 60          # 세 번째는 막힘, 첫 요청이 창을 벗어날 때까지
    assert rl.hit("b") is None        # 키마다 따로
    clock.t += 30
    assert rl.hit("a") == 30
    clock.t += 30.5
    assert rl.hit("a") is None        # 첫 요청이 창을 벗어남


def _limited_app(settings, issuer, users_file, clock, per_user=2, total=5):
    erp = create_fake_erp(PACK, demo_password=PASSWORD, delegation_public_key=issuer.public_pem(),
                          service_login_secret=SERVICE)
    s = dataclasses.replace(settings, slack_bridge_secret=BRIDGE, slack_users_file=users_file,
                            erp_service_login_secret=SERVICE, slack_login_per_user_per_minute=per_user,
                            slack_login_per_minute=total)
    app = create_app(s, erp_transport=httpx.ASGITransport(app=erp), issuer=issuer)
    return app


def test_per_user_limit_is_429_with_retry_after_and_audited_once(settings, issuer, users_file):
    clock = Clock()
    app = _limited_app(settings, issuer, users_file, clock)
    with TestClient(app) as c:
        c.app_ref = app
        app.state.slack_limits.set_clock(clock)
        assert [_login(c).status_code for _ in range(2)] == [200, 200]
        r = _login(c)
        assert r.status_code == 429 and r.json()["type"] == "urn:problem:rate-limited"
        assert int(r.headers["retry-after"]) == 60
        assert _login(c).status_code == 429
        assert _login(c, "U2").status_code == 200        # 다른 사용자는 됨
        limited = [e for e in _audit(c) if e["problemType"] == "urn:problem:rate-limited"]
        assert len(limited) == 1 and limited[0]["result"] == "denied"   # 같은 창에서는 한 번만 남김
        clock.t += 61
        assert _login(c).status_code == 200


def test_total_limit_counts_wrong_secrets(settings, issuer, users_file):
    clock = Clock()
    app = _limited_app(settings, issuer, users_file, clock, per_user=100, total=3)
    with TestClient(app) as c:
        c.app_ref = app
        app.state.slack_limits.set_clock(clock)
        assert [_login(c, secret="bad").status_code for _ in range(3)] == [401, 401, 401]
        assert _login(c).status_code == 429             # 맞는 비밀값도 전체 상한에 걸림
        assert sum(1 for e in _audit(c) if e["problemType"] == "urn:problem:unauthorized") == 3


def test_settings_read_rate_limits(monkeypatch):
    from gateway.config import Settings

    monkeypatch.delenv("SLACK_LOGIN_PER_USER_PER_MINUTE", raising=False)
    monkeypatch.delenv("SLACK_LOGIN_PER_MINUTE", raising=False)
    s = Settings.from_env()
    assert (s.slack_login_per_user_per_minute, s.slack_login_per_minute) == (10, 60)
    monkeypatch.setenv("SLACK_LOGIN_PER_USER_PER_MINUTE", "3")
    monkeypatch.setenv("SLACK_LOGIN_PER_MINUTE", "7")
    s = Settings.from_env()
    assert (s.slack_login_per_user_per_minute, s.slack_login_per_minute) == (3, 7)
