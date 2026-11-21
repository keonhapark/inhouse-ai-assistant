"""다섯 조건 실행기(eval/protocol.md 1·8절).

같은 시나리오를 조건마다 반복해서 돌리고 회차마다 한 줄(RunRow)을 남깁니다. 순서는 회차 → 시나리오 → 조건이라,
비용 상한으로 멈춰도 이미 끝난 시나리오는 다섯 조건이 짝을 이룹니다.
"""

from __future__ import annotations

import json
import platform
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from harness.conversation import CONNECTION_ERRORS
from harness.erp import ErpClient
from harness.paths import ROOT
from harness.run import run_once
from harness.sut import ChatSystem

CONDITIONS = ("no_guard", "write_blocked", "approve_all", "baseline_tools", "full")
# 하네스 조건: 대상 시스템에는 계약 조건(값)으로 보내고 하네스 승인자만 바꿉니다(결정 0006 민감도 분석)
HARNESS_CONDITIONS = {"full_always_approve": "full"}
# 실행·보고서 순서. 하네스 조건은 그 계약 조건 바로 뒤에 둡니다
RUN_CONDITIONS = ("no_guard", "write_blocked", "approve_all", "baseline_tools", "full", "full_always_approve")


def system_condition(condition: str) -> str:
    """대상 시스템(gateway X-Eval-Condition)에 보낼 계약 조건."""
    return HARNESS_CONDITIONS.get(condition, condition)
# 실행 환경 문제로 끝나지 못한 같은 회차를 다시 돌리는 상한. 넘으면 "실패로 끝남"으로 확정합니다(eval/protocol.md 2절)
MAX_RETRIES = 2

# (조건, 시드) → 그 조건으로 설정된 대상 시스템
SystemFactory = Callable[[str, int], ChatSystem]
# 회차마다 부릅니다. 시작 상태로 되돌린 erp를 돌려줍니다
ErpFactory = Callable[[], ErpClient]
# 모델 서버가 응답하면 True
HealthCheck = Callable[[], bool]


@dataclass
class RunRow:
    scenario_id: str
    set: str
    kind: str
    concern_type: str | None
    reactive: bool | None
    author: str
    expected_agent: str | None
    condition: str
    repeat: int
    seed: int
    outcome: str
    passed: bool
    incidents: list[str] = field(default_factory=list)  # "code: detail"
    shortfalls: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    route: str = "none"
    routed_agent: str | None = None
    executed_then_undone: bool = False
    forbidden_attempts: int = 0
    approvals_requested: int = 0
    missed_risks: int = 0
    unnecessary_approvals: int = 0
    duration_s: float | None = None
    cost_usd: float | None = None
    error: str | None = None
    # 실행 환경 문제로 끝나지 못함. 이어 돌릴 때 MAX_RETRIES번까지 다시 돌립니다
    retry: bool = False
    # 실제로 쓴 모델: "이름(위치)". 이벤트의 model과 외부 요청 기록의 model에서 모읍니다
    models: list[str] = field(default_factory=list)
    # 이 회차를 돌린 하네스 커밋(git HEAD)·미커밋 여부, 대상 시스템 스택을 빌드한 커밋(설정 stackCommit), 팩 단계.
    # 나눠·이어 돌린 회차가 같은 시스템에서 돌았는지 보려고 회차마다 남깁니다. 이 필드가 생기기 전 기록은 None
    commit: str | None = None
    dirty: bool | None = None
    stack_commit: str | None = None
    pack_stage: int | None = None
    # 하네스 승인자(always_approve, always_reject, intent)와 승인자가 거절한 카드 수
    approver: str | None = None
    approvals_rejected: int = 0
    # 회차 시간 동안 대화 ID 없이 외부로 나간 요청 수(#294, 판정 밖 경고)
    orphan_external: int | None = None
    # 이 회차를 돌릴 때 rag에 주입 문서 파일(RAG_EXTRA_DOCS)이 켜져 있었는지. 확인하지 못했으면 None
    injected_docs: bool | None = None
    # 이 회차를 돌릴 때 대조한 확인 셋 묶음(RunMeta.bundle과 같은 문자열). 묶음 없이 돌렸으면 None
    bundle: str | None = None


@dataclass
class RunMeta:
    commit: str
    dirty: bool
    machine: str
    started_at: str
    finished_at: str = ""
    model: str | None = None
    pack: str | None = None
    # packs/<id>/pack.yaml의 version("id 버전", 여럿이면 쉼표)
    pack_version: str | None = None
    # 대상 시스템을 띄운 팩 단계(compose PACK_STAGE). 설정 packStage로 받습니다
    pack_stage: int | None = None
    conditions: list[str] = field(default_factory=list)
    repeats: int = 3
    base_seed: int = 0
    cost_cap_usd: float | None = None
    cost_spent_usd: float = 0.0
    cost_unknown_runs: int = 0
    # 실행 환경 문제로 다시 돌린 횟수(회차 기록 파일에서 같은 회차가 두 번째 이상 나온 줄 수)
    retried_runs: int = 0
    planned_runs: int = 0
    done_runs: int = 0
    complete: bool = False
    stopped_reason: str | None = None
    notes: list[str] = field(default_factory=list)
    # 고치는 데 쓴 셋(결정 0005). 보고서는 이 셋의 보호 지표를 참고로만 적습니다. 설정 tunedSets
    tuned_sets: list[str] = field(default_factory=list)
    # 모델 교체 회귀(#107·#346): gateway X-Eval-Model-Override 값. 설정 gateway.modelOverride
    model_override: str | None = None
    # 보고서에 남길 모델 설정(승인자·기기·reasoning_effort 등, 이름=값). 설정 modelSettings
    model_settings: dict[str, str] = field(default_factory=dict)
    # 확인 셋 묶음 해시 확인 결과(run --bundle, contracts/eval/confirm-sets.md). 예: "confirm-v1 `<해시>` = 계약 표(...)"
    bundle: str | None = None


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _row(scenario: dict[str, Any], condition: str, repeat: int, seed: int) -> RunRow:
    return RunRow(scenario_id=scenario["id"], set=scenario["set"], kind=scenario["kind"],
                  concern_type=scenario.get("concernType"), reactive=scenario.get("reactive"),
                  author=scenario["author"], expected_agent=scenario.get("expectedAgent"),
                  condition=condition, repeat=repeat, seed=seed, outcome="failed", passed=False)


def used_models(events: list[dict[str, Any]], external_models: list[str]) -> list[str]:
    got = {f"{e['model']['name']}({e['model'].get('location', '?')})" for e in events
           if isinstance(e.get("model"), dict) and e["model"].get("name")}
    got |= {f"{m}(외부 요청 기록)" for m in external_models}
    return sorted(got)


def run_signature(row: RunRow) -> tuple[str | None, str | None, int | None]:
    """같은 시스템에서 돌았는지 비교하는 값: (하네스 커밋, 스택 커밋, 팩 단계)."""
    return row.commit, row.stack_commit, row.pack_stage


def signature_counts(rows: list[RunRow]) -> dict[tuple[str | None, str | None, int | None], int]:
    out: dict[tuple[str | None, str | None, int | None], int] = {}
    for r in rows:
        out[run_signature(r)] = out.get(run_signature(r), 0) + 1
    return out


def pack_versions(pack_ids: list[str]) -> str:
    out = []
    for pid in pack_ids:
        f = ROOT / "packs" / pid / "pack.yaml"
        version = yaml.safe_load(f.read_text(encoding="utf-8")).get("version") if f.exists() else None
        out.append(f"{pid} {version or '버전 모름'}")
    return ", ".join(out)


def run_one(scenario: dict[str, Any], condition: str, repeat: int, seed: int, system_factory: SystemFactory,
            erp_factory: ErpFactory, time_limit_s: float, health_check: HealthCheck | None = None) -> RunRow:
    row = _row(scenario, condition, repeat, seed)
    try:
        record, v = run_once(scenario, system_factory(condition, seed), erp_factory(), time_limit_s=time_limit_s,
                             condition=condition)
    except Exception as e:  # noqa: BLE001 - setup·초기화 실패도 "실패로 끝남" 한 줄로 남깁니다
        row.error = f"{type(e).__name__}: {e}"
        row.shortfalls.append("실행 오류(setup 또는 erp 초기화)")
        if isinstance(e, CONNECTION_ERRORS):
            row.retry = True
            row.notes.append("실행 환경 문제: erp 연결 실패")
        return row
    row.outcome, row.passed = v.outcome, v.passed
    row.incidents = [f"{f.code}: {f.detail}" for f in v.incidents]
    row.shortfalls, row.notes = v.shortfalls, v.notes
    row.route, row.executed_then_undone = v.route, v.executed_then_undone
    row.forbidden_attempts = v.forbidden_attempts
    row.approvals_requested = v.approvals.requested
    row.missed_risks, row.unnecessary_approvals = v.approvals.missed_risks, v.approvals.unnecessary
    row.routed_agent = next((e.get("route", {}).get("agentId") for e in record.events if e.get("type") == "route"),
                            None)
    row.duration_s, row.cost_usd, row.error = record.duration_s, record.cost_usd, record.error
    row.models = used_models(record.events, record.external_models)
    row.orphan_external = record.orphan_external
    row.approver = record.approver
    row.approvals_rejected = sum(d.decision == "reject" for d in record.approval_decisions)
    if record.env_failure:
        row.retry = True
        row.notes.append(f"실행 환경 문제: {record.env_failure}")
    elif health_check is not None and not health_check():
        # 로컬 모델이 끊기면 대상 시스템이 오류 없이 외부 모델로 처리할 수 있어, 오류가 없어도 회차마다 확인합니다
        row.retry = True
        row.notes.append("실행 환경 문제: 회차 뒤 모델 서버 상태 확인 실패")
    return row


def run_matrix(scenarios: list[dict[str, Any]], system_factory: SystemFactory, erp_factory: ErpFactory, *,
               conditions: tuple[str, ...] | list[str] = CONDITIONS, repeats: int = 3, base_seed: int = 0,
               cost_cap_usd: float | None = None, time_limit_s: float = 300, model: str | None = None,
               on_row: Callable[[RunRow], None] | None = None,
               done_rows: list[RunRow] | None = None, max_runs: int | None = None,
               started_at: str | None = None, health_check: HealthCheck | None = None,
               prior_cost_usd: float = 0.0, pack_stage: int | None = None,
               stack_commit: str | None = None,
               injected_docs: bool | None = None,
               bundle: str | None = None) -> tuple[list[RunRow], RunMeta]:
    """done_rows는 앞서 끝낸 회차입니다(이어 돌리기). 같은 (시나리오, 조건, 회차)는 다시 돌리지 않습니다.
    max_runs는 이번에 새로 돌릴 회차 수 상한입니다(나눠 돌리기). prior_cost_usd는 done_rows에 없는 앞선 시도
    (다시 돌린 회차)의 비용으로, 비용 상한에 같이 셉니다. health_check는 재시도 가능한 오류가 났을 때 모델 서버가
    살아 있는지 봅니다. 없으면 그런 회차도 "실패로 끝남"으로 둡니다."""
    unknown = [c for c in conditions if c not in RUN_CONDITIONS]
    if unknown:
        raise ValueError(f"계약에 없는 조건: {unknown}")
    packs = sorted({s["pack"] for s in scenarios})
    meta = RunMeta(commit=_git("rev-parse", "HEAD"), dirty=bool(_git("status", "--porcelain", "--untracked-files=no")),
                   machine=f"{platform.platform()} {platform.machine()}", started_at=started_at or _now(), model=model,
                   pack=",".join(packs), pack_version=pack_versions(packs), pack_stage=pack_stage,
                   conditions=list(conditions), repeats=repeats, base_seed=base_seed,
                   cost_cap_usd=cost_cap_usd, planned_runs=len(scenarios) * len(conditions) * repeats)
    meta.cost_spent_usd = prior_cost_usd
    rows: list[RunRow] = list(done_rows or [])
    done_keys = {(r.scenario_id, r.condition, r.repeat) for r in rows}
    # 나눠 돌린 묶음(--injected-docs only·exclude)을 같은 결과 파일에 이으면 done_rows에 이번 계획 밖 회차가
    # 있습니다. 계획 회차는 이번 계획과 앞선 회차의 합집합으로 셉니다.
    plan_keys = {(s["id"], c, rep) for rep in range(1, repeats + 1) for s in scenarios for c in conditions}
    meta.planned_runs = len(plan_keys | done_keys)
    for r in rows:
        if r.cost_usd is None:
            meta.cost_unknown_runs += 1
        else:
            meta.cost_spent_usd += r.cost_usd
    new_runs = 0
    for repeat in range(1, repeats + 1):
        seed = base_seed + repeat
        for scenario in scenarios:
            if cost_cap_usd is not None and meta.cost_spent_usd >= cost_cap_usd:
                meta.stopped_reason = (f"비용 상한 {cost_cap_usd}달러에 닿아 {repeat}회차 {scenario['id']} 앞에서 "
                                       "멈췄습니다")
                break
            for condition in conditions:
                if (scenario["id"], condition, repeat) in done_keys:
                    continue
                if max_runs is not None and new_runs >= max_runs:
                    meta.stopped_reason = f"나눠 돌리기: 이번 실행은 {max_runs}회차까지 돌렸습니다"
                    break
                if health_check is not None and not health_check():
                    meta.stopped_reason = (f"모델 서버가 응답하지 않아 {repeat}회차 {scenario['id']} {condition} 앞에서 "
                                           "멈췄습니다. 실행 환경을 되살린 뒤 이어 돌립니다")
                    break
                new_runs += 1
                row = run_one(scenario, condition, repeat, seed, system_factory, erp_factory, time_limit_s,
                              health_check)
                row.commit, row.dirty, row.stack_commit, row.pack_stage = (meta.commit, meta.dirty, stack_commit,
                                                                           pack_stage)
                row.injected_docs = injected_docs
                row.bundle = bundle
                rows.append(row)
                if row.cost_usd is None:
                    meta.cost_unknown_runs += 1
                else:
                    meta.cost_spent_usd += row.cost_usd
                if on_row:
                    on_row(row)
            if meta.stopped_reason:
                break
        if meta.stopped_reason:
            break
    meta.done_runs = len(rows)
    meta.complete = meta.done_runs == meta.planned_runs
    if meta.cost_unknown_runs:
        meta.notes.append(f"비용을 알 수 없는 회차 {meta.cost_unknown_runs}개는 비용 상한 계산에서 빠졌습니다")
    if meta.dirty:
        meta.notes.append("커밋하지 않은 변경이 있는 상태에서 실행했습니다")
    meta.finished_at = _now()
    return rows, meta


def save_run(rows: list[RunRow], meta: RunMeta, path: Path, summary: dict[str, Any] | None = None) -> None:
    """summary는 report.summarize의 값입니다(contracts/eval/report.schema.json)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"meta": asdict(meta), "rows": [asdict(r) for r in rows]}
    if summary is not None:
        data["summary"] = summary
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _attempts(path: Path) -> dict[tuple[str, str, int], list[RunRow]]:
    got: dict[tuple[str, str, int], list[RunRow]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = RunRow(**json.loads(line))
                got.setdefault((r.scenario_id, r.condition, r.repeat), []).append(r)
    return got


@dataclass
class Resume:
    done: list[RunRow]
    # done에 들어가지 않은 시도(다시 돌린 것, 다시 돌릴 것)의 비용
    prior_cost_usd: float


def load_rows_jsonl(path: Path, max_retries: int = MAX_RETRIES) -> Resume:
    """실행 중에 한 줄씩 쓴 회차 기록을 읽습니다. 같은 회차가 여러 번 있으면 마지막 것을 씁니다.
    마지막 시도가 실행 환경 문제(retry)이고 다시 돌린 횟수가 max_retries보다 적으면 다시 돌리도록 뺍니다.
    상한에 닿았으면 "실패로 끝남"으로 확정합니다."""
    done: list[RunRow] = []
    prior = 0.0
    for attempts in _attempts(path).values():
        last = attempts[-1]
        earlier = attempts[:-1]
        if last.retry and len(earlier) < max_retries:
            earlier = attempts
        else:
            if last.retry:
                last.retry = False
                last.shortfalls.append(f"실행 환경 문제로 {max_retries}번 다시 돌려도 끝나지 못해 실패로 확정")
            done.append(last)
        prior += sum(a.cost_usd or 0.0 for a in earlier)
    return Resume(done=done, prior_cost_usd=prior)


def count_retries(path: Path) -> int:
    """회차 기록 파일에서 같은 회차를 다시 돌린 횟수입니다."""
    return sum(len(a) - 1 for a in _attempts(path).values())


def load_run(path: Path) -> tuple[list[RunRow], RunMeta]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [RunRow(**r) for r in data["rows"]], RunMeta(**data["meta"])
