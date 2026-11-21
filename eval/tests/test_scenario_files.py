"""eval/scenarios의 시나리오가 계약대로 돌 수 있는지 봅니다: setup이 가짜 erp에서 성공하고, dbAssertions가 조회 오류 없이 평가됩니다."""

import pytest

from harness.db import check_db
from harness.erp import ErpClient
from harness.paths import EVAL_DIR
from harness.scenario import load_scenarios
from harness.setup import run_setup
from tests.conftest import PASSWORD, new_fake_erp

SCENARIOS = load_scenarios(EVAL_DIR / "scenarios")


def test_dev_concern_types():
    dev = [s for s in SCENARIOS if s["set"] == "dev"]
    # 1·2단계 개발 셋은 우려 시나리오만, 3단계(stage3.yaml, dev-s3-*)는 새 에이전트 정상 업무도 둡니다(#386)
    assert all(s["kind"] == "concern" for s in dev if not s["id"].startswith("dev-s3-"))
    assert len({s["concernType"] for s in dev if s["kind"] == "concern"}) >= 3


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
    if scenario["kind"] == "concern":
        # 아무것도 하지 않은 상태는 사고가 아니어야 합니다(그렇지 않으면 막아도 사고로 판정됨)
        assert all(r.ok for r in results), [r.detail for r in results if not r.ok]


def _load_yaml(path):
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _check(schema_name, data):
    import json

    from jsonschema import Draft202012Validator

    from harness.paths import CONTRACTS
    schema = json.loads((CONTRACTS / "eval" / schema_name).read_text(encoding="utf-8"))
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(data)]
    assert not errors, errors


def test_dev_set_counts():
    from collections import Counter
    base = Counter(s["concernType"] for s in SCENARIOS if s["set"] == "dev" and not s["id"].startswith("dev-s3-"))
    assert base == {"leak": 12, "out_of_scope_doc": 12, "cross_dept_bypass": 12, "wrong_execution": 12, "injection": 12}
    s3 = Counter(s.get("concernType") or "normal" for s in SCENARIOS if s["id"].startswith("dev-s3-"))
    assert s3 == {"normal": 4, "cross_dept_bypass": 2, "out_of_scope_doc": 1, "leak": 3, "wrong_execution": 1,
                  "injection": 2}


def test_markers_file_matches_scenarios():
    markers = _load_yaml(EVAL_DIR / "markers/dev.yaml")
    _check("markers.schema.json", markers)
    planted = {m for ms in markers["markers"].values() for m in ms}
    for s in SCENARIOS:
        if s["set"] == "dev" and s.get("concernType") in ("out_of_scope_doc", "cross_dept_bypass") and \
                any(m.startswith("DEV-MARKER-") for m in s["expect"].get("markers", [])):
            # 권한 밖 문서 시나리오의 표지는 모두 제한 문서에 심은 것이어야 판정이 됩니다
            assert set(s["expect"]["markers"]) <= planted, s["id"]


def test_injected_docs_file_matches_scenarios():
    docs = _load_yaml(EVAL_DIR / "injections/dev.yaml")
    _check("injected-docs.schema.json", docs)
    by_id = {d["docId"]: d for d in docs["documents"]}
    used = [c for s in SCENARIOS for c in s.get("injectedContent", []) if c["where"] == "document"]
    assert used
    for c in used:
        assert c["ref"] in by_id and c["content"] == by_id[c["ref"]]["body"]
