"""시나리오 setup 실행: 대화 전에 erp에 상태를 만들어 둡니다."""

from __future__ import annotations

from typing import Any

from harness.erp import ErpClient
from harness.scenario import substitute


def run_setup(scenario: dict[str, Any], erp: ErpClient) -> dict[str, str]:
    """setup 단계를 차례로 실행하고 saveAs로 저장한 리소스 ID를 돌려줍니다.

    쓰기 결과(ActionResult)면 resource.id를, 아니면 응답의 id를 저장합니다. 하나라도 실패하면
    ErpCallError로 멈춥니다. setup이 실패한 시나리오는 판정하지 않고 실행 오류로 셉니다.
    """
    variables: dict[str, str] = {}
    for step in scenario.get("setup", []):
        step = substitute(step, variables)
        result = erp.call_ok(step["as"], step["operation"], step.get("params"), step["body"])
        if "saveAs" in step:
            rid = None
            if isinstance(result, dict):
                resource = result.get("resource")
                rid = resource.get("id") if isinstance(resource, dict) else None
                rid = rid or result.get("id")
            if not rid:
                raise ValueError(f"setup {step['operation']} 결과에서 저장할 id를 찾지 못했습니다")
            variables[step["saveAs"]] = str(rid)
    return variables
