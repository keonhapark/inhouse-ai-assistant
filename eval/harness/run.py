"""시나리오 한 회차: setup → 대화 → 기록 수집 → DB 판정 → 사고 판정."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from harness.conversation import run_conversation
from harness.db import check_db
from harness.erp import ErpClient
from harness.judge import Verdict, judge
from harness.record import RunRecord
from harness.scenario import substitute
from harness.setup import run_setup
from harness.sut import ChatSystem


def run_once(scenario: dict[str, Any], system: ChatSystem, erp: ErpClient, *,
             time_limit_s: float = 300, condition: str | None = None) -> tuple[RunRecord, Verdict]:
    variables = run_setup(scenario, erp)
    expect = dict(scenario["expect"])
    if "approvable" in expect:
        expect["approvable"] = substitute(expect["approvable"], variables)
    scenario = {**scenario, "turns": substitute(scenario["turns"], variables), "expect": expect}
    started = time.monotonic()
    since = datetime.now(timezone.utc)
    record = run_conversation(scenario, system, time_limit_s=time_limit_s, condition=condition)
    record.duration_s = time.monotonic() - started
    orphans = getattr(system, "orphan_external", None)
    if orphans is not None:
        try:
            record.orphan_external = orphans(since, datetime.now(timezone.utc))
        except Exception:  # noqa: BLE001 - 경고용 집계라 실패해도 판정은 계속합니다
            record.orphan_external = None
    if record.conversation_id:
        try:
            got = system.collect(record.conversation_id)
            record.audit_events = got.audit_events
            record.external_requests = got.external_requests
            record.external_models = got.external_models
            record.logs = got.logs
            record.cost_usd = got.cost_usd
        except Exception as e:  # noqa: BLE001
            record.error = record.error or f"기록 수집 실패: {type(e).__name__}: {e}"
    # 대화 직후, 되돌리기 전에 봅니다
    db = check_db(scenario["expect"].get("dbAssertions", []), erp, variables)
    return record, judge(scenario, record, db)
