"""위임 토큰 문자열을 표지로 써서 로그에 남지 않는지 봅니다(기획서 5-4)."""

import logging

import base64

from gateway.redact import MASK, scrub


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).rstrip(b"=").decode()


def test_issue_and_use_do_not_log_token(caplog, client, login, issue, staff_no, erp_http):
    caplog.set_level(logging.DEBUG)
    emp_jwt = login(staff_no)
    issued = issue(emp_jwt, "hr")
    client.get("/api/me", headers={"Authorization": f"Bearer {emp_jwt}"})
    logging.getLogger("gateway.test").info("대화 시작 headers=%s", {"X-Delegation-Token": issued.token})
    logging.getLogger("gateway.test").warning(f"직원 토큰 Bearer {emp_jwt}")

    assert caplog.records, "로그가 하나도 없으면 시험이 의미가 없습니다"
    for rec in caplog.records:
        msg = rec.getMessage()
        assert issued.token not in msg
        assert emp_jwt not in msg
    assert issued.claims["jti"] in caplog.text  # 발급 기록은 jti로 남습니다
    assert MASK in caplog.text


def test_scrub_masks_jwt_and_bearer():
    # 비밀값 검사(gitleaks)가 소스의 JWT 모양을 잡으므로 실행할 때 만듭니다.
    jwt_like = ".".join(_b64(p) for p in ('{"alg":"ES256"}', '{"sub":"E0001"}', "signature-value-x"))
    assert scrub(f"token={jwt_like} end") == f"token={MASK} end"
    assert scrub("Authorization: Bearer abcdefghijklmnopqrstuv") == f"Authorization: Bearer {MASK}"
    assert scrub("평문 문장은 그대로입니다") == "평문 문장은 그대로입니다"
