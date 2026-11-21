"""장애 목록과 주입 명령(가짜 docker)을 봅니다. 실제 주입은 세션 스택에서 incident.run으로 합니다."""

from __future__ import annotations

import subprocess

import pytest

from incident import faults as F
from incident.stack import SERVICES, Stack
from incident.tickets import TEMPLATES

KINDS = {"dependency_down", "lock_contention", "resource_exhaustion", "dependency_timeout", "data_corruption",
         "bad_config"}


class FakeDocker:
    def __init__(self, outputs: dict[str, str] | None = None):
        self.calls: list[tuple[list[str], dict[str, str] | None]] = []
        self.outputs = outputs or {}

    def __call__(self, args, *, env=None, input=None, check=True, timeout=None):
        self.calls.append((args, env))
        out = next((v for k, v in self.outputs.items() if k in " ".join(args)), "")
        return subprocess.CompletedProcess(args, 0, out, "")


def test_catalog_is_complete() -> None:
    ids = [f.id for f in F.CATALOG]
    assert len(ids) == len(set(ids))
    for f in F.CATALOG:
        assert f.root_service in SERVICES
        assert f.kind in KINDS
        assert f.duration_s > 0
        assert len(TEMPLATES[f.id]) >= 3, "장애마다 티켓 문장이 셋 이상 있어야 합니다"
    assert set(TEMPLATES) == set(ids)


def test_ticket_text_names_symptoms_not_causes() -> None:
    # 직원은 원인을 모릅니다. 원인 서비스 이름이 티켓에 들어가면 분석 평가가 쉬워집니다.
    leaks = ("postgres", "postgresql", "litellm", "gateway", "rag", "임베딩", "캐시", "잠금", "메모리", "db")
    for fault_id, texts in TEMPLATES.items():
        for title, body in texts:
            text = f"{title} {body}".lower()
            assert not any(w in text for w in leaks), (fault_id, title)


def test_injection_only_touches_session_containers() -> None:
    docker = FakeDocker({"embeddings": "/repo/rag/.cache/embeddings-local-embed.json\n",
                         "Health": "healthy"})
    stack = Stack(1, runner=docker)
    for f in F.CATALOG:
        if f.id in ("db_down", "erp_memory", "db_lock"):
            continue  # 복구가 erp HTTP를 기다림(실제 스택에서 확인)
        f.inject(stack, 1)
        f.recover(stack)
    named = [a for args, _ in docker.calls for a in args if a.startswith("iaa-")]
    assert named and all(a.startswith("iaa-s1-") or a.startswith("iaa-s1") for a in named)
    compose = [args for args, _ in docker.calls if args[:2] == ["docker", "compose"]]
    assert all(args[args.index("-p") + 1] == "iaa-s1" for args in compose)


def test_bad_config_overrides_key_only_for_injection() -> None:
    docker = FakeDocker({"Health": "healthy"})
    stack = Stack(1, runner=docker)
    F.by_id("gateway_bad_config").inject(stack, 1)
    F.by_id("gateway_bad_config").recover(stack)
    (_, env_inject), (_, env_recover) = [(a, e) for a, e in docker.calls if a[:2] == ["docker", "compose"]]
    assert env_inject["LITELLM_MASTER_KEY"] == "sk-wrong-key-deployed"
    assert env_recover.get("LITELLM_MASTER_KEY") != "sk-wrong-key-deployed"


def test_unknown_fault() -> None:
    with pytest.raises(KeyError):
        F.by_id("nope")
