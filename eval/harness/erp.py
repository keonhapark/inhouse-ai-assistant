"""operationId로 erp를 부르는 얇은 클라이언트.

setup과 dbAssertions는 erp operationId로 적혀 있으므로, contracts/openapi/erp.yaml에서 메서드·경로를 찾아 부릅니다.
사람 화면 경로(직원 JWT)로 부릅니다.
"""

from __future__ import annotations

import os
import uuid
from functools import cache
from typing import Any

import httpx
import yaml

from harness.paths import ERP_OPENAPI


class ErpCallError(RuntimeError):
    def __init__(self, operation: str, status: int, body: str) -> None:
        self.operation = operation
        self.status = status
        self.body = body
        super().__init__(f"{operation}: {status} {body[:300]}")


@cache
def operations() -> dict[str, dict[str, Any]]:
    spec = yaml.safe_load(ERP_OPENAPI.read_text(encoding="utf-8"))
    ops: dict[str, dict[str, Any]] = {}
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if isinstance(op, dict) and "operationId" in op:
                ops[op["operationId"]] = {"method": method.upper(), "path": path, "write": bool(op.get("x-write"))}
    return ops


class ErpClient:
    def __init__(self, client: httpx.Client, password: str | None = None) -> None:
        self.c = client
        self.password = password or os.environ.get("ERP_DEMO_PASSWORD", "demo")
        self._tokens: dict[str, str] = {}

    def token(self, employee: str) -> str:
        if employee not in self._tokens:
            r = self.c.post("/auth/login", json={"employeeNo": employee, "password": self.password})
            if r.status_code != 200:
                raise ErpCallError("login", r.status_code, r.text)
            self._tokens[employee] = r.json()["accessToken"]
        return self._tokens[employee]

    def call(self, as_: str, operation: str, params: dict[str, Any] | None = None,
             body: Any = None) -> httpx.Response:
        """경로 변수는 params에서 채우고, 남은 params는 쿼리로 보냅니다. 쓰기에는 멱등 키를 붙입니다."""
        try:
            op = operations()[operation]
        except KeyError:
            raise ErpCallError(operation, 0, "erp 계약에 없는 operationId") from None
        params = dict(params or {})
        path = op["path"]
        for name in [p[1:-1] for p in path.split("/") if p.startswith("{")]:
            if name not in params:
                raise ErpCallError(operation, 0, f"경로 변수 {name}가 params에 없음")
            path = path.replace("{" + name + "}", str(params.pop(name)))
        headers = {"Authorization": f"Bearer {self.token(as_)}"}
        if op["write"] and not params.get("dryRun"):
            headers["Idempotency-Key"] = uuid.uuid4().hex
        return self.c.request(op["method"], path, params=params or None, json=body, headers=headers)

    def call_ok(self, as_: str, operation: str, params: dict[str, Any] | None = None,
                body: Any = None) -> Any:
        r = self.call(as_, operation, params, body)
        if r.status_code >= 300:
            raise ErpCallError(operation, r.status_code, r.text)
        return r.json()
