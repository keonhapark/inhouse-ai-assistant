"""주입할 장애 목록. 장애마다 정답 원인(서비스·종류)과 주입·복구 방법을 갖습니다.

모든 주입은 세션 스택(iaa-s<번호>) 컨테이너에만 합니다. 디스크 가득은 도커 VM 디스크를 다른 세션과 같이 쓰므로
넣지 않았습니다(README).
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from typing import Callable

from incident.stack import Stack

LOCKED_TABLES = "approval_document, room_reservation, leave_balance, ticket"
# rag 이미지는 RAG_CACHE_DIR로 캐시 위치를 정합니다. 없으면 rag 기본값입니다.
RAG_CACHE = "${RAG_CACHE_DIR:-/repo/rag/.cache}"


@dataclass(frozen=True)
class Fault:
    id: str
    title: str
    root_service: str
    """정답 원인 서비스(compose 서비스 이름)."""
    kind: str
    """정답 원인 종류: dependency_down, lock_contention, resource_exhaustion, dependency_timeout,
    data_corruption, bad_config."""
    duration_s: int
    inject: Callable[[Stack, int], None]
    recover: Callable[[Stack], None]


def wait_healthy(stack: Stack, service: str, timeout_s: int = 300) -> None:
    """컨테이너 상태가 healthy(헬스체크가 없으면 running)가 될 때까지 기다립니다."""
    deadline = time.monotonic() + timeout_s
    fmt = "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}"
    while time.monotonic() < deadline:
        out = stack.docker("inspect", "-f", fmt, stack.container(service), check=False).stdout.strip()
        if out in ("healthy", "running"):
            return
        time.sleep(2)
    raise TimeoutError(f"{service}가 {timeout_s}초 안에 정상으로 돌아오지 않았습니다")


def wait_erp(stack: Stack, timeout_s: int = 300) -> None:
    """erp에는 compose 헬스체크가 없어 /health를 직접 봅니다."""
    import httpx

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{stack.erp_url}/health", timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise TimeoutError(f"erp가 {timeout_s}초 안에 돌아오지 않았습니다")


# ---------- 장애별 주입·복구 ----------

def _db_down(stack: Stack, _: int) -> None:
    stack.docker("stop", "-t", "2", stack.container("postgres"))


def _db_down_recover(stack: Stack) -> None:
    stack.docker("start", stack.container("postgres"))
    wait_healthy(stack, "postgres")
    wait_erp(stack)


def _db_lock(stack: Stack, duration_s: int) -> None:
    # 업무 표를 배타 잠금으로 잡고 duration 동안 놓지 않습니다. erp 요청은 잠금을 기다리다 늦거나 실패합니다.
    sql = f"begin; lock table {LOCKED_TABLES} in access exclusive mode; select pg_sleep({duration_s}); commit;"
    stack.docker("exec", "-d", stack.container("postgres"), "psql", "-U", "iaa", "-d", "erp", "-c", sql)


def _db_lock_recover(stack: Stack) -> None:
    # 잠금 세션이 아직 남아 있으면 끝냅니다(pg_sleep을 부르는 연결).
    sql = "select pg_terminate_backend(pid) from pg_stat_activity where query like '%pg_sleep%' and pid <> pg_backend_pid();"
    stack.docker("exec", stack.container("postgres"), "psql", "-U", "iaa", "-d", "erp", "-c", sql, check=False)
    wait_erp(stack)


def _erp_memory(stack: Stack, _: int) -> None:
    # 실행 중인 erp 컨테이너의 메모리 상한을 JVM이 쓰는 양보다 낮춥니다. 커널이 프로세스를 죽이거나 GC가 멈춥니다.
    stack.docker("update", "--memory", "160m", "--memory-swap", "160m", stack.container("erp"))


def _erp_memory_recover(stack: Stack) -> None:
    stack.docker("update", "--memory", "4g", "--memory-swap", "4g", stack.container("erp"), check=False)
    state = stack.docker("inspect", "-f", "{{.State.Status}}", stack.container("erp"), check=False).stdout.strip()
    if state != "running":
        stack.docker("start", stack.container("erp"))
    wait_erp(stack)


def _llm_timeout(stack: Stack, _: int) -> None:
    # LLM 출구(LiteLLM) 프로세스를 멈춥니다. 연결은 받지만 답하지 않아 gateway가 시간 초과로 끝납니다.
    stack.docker("pause", stack.container("litellm"))


def _llm_timeout_recover(stack: Stack) -> None:
    stack.docker("unpause", stack.container("litellm"), check=False)
    wait_healthy(stack, "litellm")


_rag_files: dict[str, list[str]] = {}


def _rag_cache_files(stack: Stack) -> list[str]:
    out = stack.docker("exec", stack.container("rag"), "sh", "-c", f'ls "{RAG_CACHE}"/embeddings-*.json', check=False)
    return [line.strip() for line in out.stdout.splitlines() if line.strip().endswith(".json")]


def _put(stack: Stack, path: str, content: str) -> None:
    """컨테이너가 멈춰 있어도 되도록 docker cp로 파일을 덮어씁니다."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(content)
    try:
        stack.docker("cp", f.name, f"{stack.container('rag')}:{path}")
    finally:
        os.unlink(f.name)


def _rag_corrupt(stack: Stack, _: int) -> None:
    # 임베딩 캐시 파일을 깨진 JSON으로 덮고 rag를 다시 띄웁니다. 시작할 때 캐시를 읽다 실패합니다.
    files = _rag_cache_files(stack)
    if not files:
        raise RuntimeError("rag 임베딩 캐시 파일이 없습니다")
    _rag_files[stack.project] = files
    for path in files:
        _put(stack, path, '{"broken')
    stack.docker("restart", "-t", "2", stack.container("rag"))


def _rag_corrupt_recover(stack: Stack) -> None:
    # 깨진 캐시를 빈 캐시로 바꾸고 다시 띄웁니다(문서를 다시 임베딩).
    for path in _rag_files.pop(stack.project, []):
        _put(stack, path, "{}")
    stack.docker("restart", "-t", "2", stack.container("rag"), check=False)
    wait_healthy(stack, "rag", timeout_s=600)


def _gateway_config(stack: Stack, _: int) -> None:
    # 틀린 LLM 출구 키로 gateway를 다시 배포합니다. LiteLLM이 401로 거절합니다.
    stack.compose("up", "-d", "--no-deps", "--force-recreate", "gateway", LITELLM_MASTER_KEY="sk-wrong-key-deployed")


def _gateway_config_recover(stack: Stack) -> None:
    stack.compose("up", "-d", "--no-deps", "--force-recreate", "--wait", "gateway")


CATALOG: tuple[Fault, ...] = (
    Fault("db_down", "PostgreSQL 중단", "postgres", "dependency_down", 60, _db_down, _db_down_recover),
    Fault("db_lock", "업무 표 배타 잠금", "postgres", "lock_contention", 60, _db_lock, _db_lock_recover),
    Fault("erp_memory", "erp 메모리 부족", "erp", "resource_exhaustion", 60, _erp_memory, _erp_memory_recover),
    Fault("llm_timeout", "LLM 출구 응답 없음", "litellm", "dependency_timeout", 90, _llm_timeout,
          _llm_timeout_recover),
    Fault("rag_corrupt", "rag 임베딩 캐시 손상", "rag", "data_corruption", 60, _rag_corrupt, _rag_corrupt_recover),
    Fault("gateway_bad_config", "gateway 잘못된 LLM 키 배포", "gateway", "bad_config", 90, _gateway_config,
          _gateway_config_recover),
)


def by_id(fault_id: str) -> Fault:
    for f in CATALOG:
        if f.id == fault_id:
            return f
    raise KeyError(fault_id)
