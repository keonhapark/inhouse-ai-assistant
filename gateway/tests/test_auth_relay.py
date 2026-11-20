def test_login_and_me_relay_erp(client, login, staff_no):
    token = login(staff_no)
    r = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["employeeNo"] == staff_no
    assert "employee" in r.json()["roles"]


def test_wrong_password_is_erp_problem(client, staff_no):
    r = client.post("/api/auth/login", json={"employeeNo": staff_no, "password": "wrong"})
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"] == "urn:problem:unauthorized"


def test_me_without_token_is_401(client):
    r = client.get("/api/me")
    assert r.status_code == 401
    assert r.json()["type"] == "urn:problem:unauthorized"


def test_login_with_non_json_body_is_422(client):
    r = client.post("/api/auth/login", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_erp_down_is_502(settings, issuer):
    import httpx
    from fastapi.testclient import TestClient

    from gateway.main import create_app

    def boom(request):
        raise httpx.ConnectError("down")

    app = create_app(settings, erp_transport=httpx.MockTransport(boom), issuer=issuer)
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"employeeNo": "x", "password": "y"})
    assert r.status_code == 502
    assert r.json()["type"] == "urn:problem:upstream-unavailable"
