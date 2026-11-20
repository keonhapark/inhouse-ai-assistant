import jwt


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/health").json() == {"status": "ok"}


def test_jwks_verifies_issued_token(client, login, issue, staff_no):
    keys = client.get("/api/.well-known/jwks.json").json()["keys"]
    assert len(keys) == 1 and keys[0]["alg"] == "ES256" and keys[0]["kty"] == "EC"
    assert "d" not in keys[0]  # 개인 키 성분이 나가지 않음

    issued = issue(login(staff_no), "assistant")
    assert jwt.get_unverified_header(issued.token)["kid"] == keys[0]["kid"]
    key = jwt.PyJWK(keys[0]).key
    claims = jwt.decode(issued.token, key, algorithms=["ES256"], audience="mcp", issuer="gateway")
    assert claims["jti"] == issued.claims["jti"]
