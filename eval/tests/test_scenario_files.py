"""eval/scenarios의 시나리오가 계약대로 돌 수 있는지 봅니다: setup이 가짜 erp에서 성공하고, dbAssertions가 조회 오류 없이 평가됩니다."""

import pytest

from harness.db import check_db
from harness.erp import ErpClient
from harness.paths import EVAL_DIR
from harness.scenario import load_scenarios
from harness.setup import run_setup
from tests.conftest import PASSWORD, new_fake_erp

SCENARIOS = load_scenarios(EVAL_DIR / "scenarios")


def test_counts():
    normal = [s for s in SCENARIOS if s["set"] == "normal"]
    assert len(normal) == 80
    assert sum(1 for s in normal if s.get("reactive")) == 40
    assert all(s["kind"] == "normal" for s in normal)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_setup_and_db_assertions_run(scenario):
    with new_fake_erp() as c:
        erp = ErpClient(c, password=PASSWORD)
        variables = run_setup(scenario, erp)
        results = check_db(scenario["expect"].get("dbAssertions", []), erp, variables)
    assert not [r.detail for r in results if "조회 실패" in r.detail]
