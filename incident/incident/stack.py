"""세션 스택(docker compose 프로젝트 iaa-s<번호>)을 다루는 얇은 층.

명령은 Runner로 돌려 시험에서 가짜로 바꿀 수 있습니다. 평가 스택(다른 세션)은 프로젝트 이름이 달라 건드리지 않습니다.
"""

from __future__ import annotations

import os
import secrets
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "infra" / "compose.yaml"

# 장애를 주입하고 로그를 모으는 서비스. web은 정적 파일이라 뺍니다.
SERVICES = ("postgres", "erp", "rag", "agent", "litellm", "gateway")


class Runner(Protocol):
    def __call__(self, args: list[str], *, env: dict[str, str] | None = None, input: str | None = None,
                 check: bool = True, timeout: float | None = None) -> subprocess.CompletedProcess[str]: ...


def run(args: list[str], *, env: dict[str, str] | None = None, input: str | None = None, check: bool = True,
        timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, env=env, input=input, check=check, timeout=timeout, capture_output=True, text=True)


def session_env(session: int) -> dict[str, str]:
    """scripts/env.sh와 같은 포트 규칙(docs/ports.md)."""
    base = 8000 + 100 * session
    return {
        "SESSION_NO": str(session), "PORT_BASE": str(base), "COMPOSE_PROJECT_NAME": f"iaa-s{session}",
        "PORT_WEB": str(base), "PORT_GATEWAY": str(base + 10), "PORT_AGENT": str(base + 20),
        "PORT_MCP": str(base + 21), "PORT_RAG": str(base + 30), "PORT_ERP": str(base + 40),
        "PORT_FAKE_ERP": str(base + 41), "PORT_LITELLM": str(base + 50), "PORT_POSTGRES": str(base + 60),
    }


LOCAL_SECRETS = Path(__file__).resolve().parents[1] / ".stack-secrets"


def local_secrets(path: Path = LOCAL_SECRETS) -> dict[str, str]:
    """.env에 없으면 이 스택 전용 LiteLLM 키를 만들어 둡니다(커밋하지 않음). gateway를 다시 띄워도 같은 키를 씁니다."""
    if not path.exists():
        path.write_text(f"LITELLM_MASTER_KEY=sk-incident-{secrets.token_hex(16)}\n", encoding="utf-8")
        path.chmod(0o600)
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


@dataclass
class Stack:
    session: int
    runner: Runner = run
    env_file: Path = ROOT / ".env"
    # 장애 실험은 로컬 모델만 씁니다. 외부 모델 키는 비워 외부로 나가지 않게 합니다.
    extra_env: dict[str, str] = field(default_factory=lambda: {"ANTHROPIC_API_KEY": ""})

    def __post_init__(self) -> None:
        if "LITELLM_MASTER_KEY=" not in (self.env_file.read_text(encoding="utf-8") if self.env_file.exists() else ""):
            self.extra_env = {**local_secrets(), **self.extra_env}

    @property
    def project(self) -> str:
        return f"iaa-s{self.session}"

    @property
    def erp_url(self) -> str:
        return f"http://localhost:{8000 + 100 * self.session + 40}/api/v1"

    def env(self, **override: str) -> dict[str, str]:
        return {**os.environ, **session_env(self.session), **self.extra_env, **override}

    def compose(self, *args: str, check: bool = True, timeout: float | None = 600,
                **override: str) -> subprocess.CompletedProcess[str]:
        cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "--env-file", str(self.env_file), "-p", self.project,
               "--profile", "full", *args]
        return self.runner(cmd, env=self.env(**override), check=check, timeout=timeout)

    def container(self, service: str) -> str:
        return f"{self.project}-{service}-1"

    def docker(self, *args: str, input: str | None = None, check: bool = True,
               timeout: float | None = 120) -> subprocess.CompletedProcess[str]:
        return self.runner(["docker", *args], env=self.env(), input=input, check=check, timeout=timeout)

    def up(self) -> None:
        self.compose("up", "-d", "--wait", "--build", timeout=1800)

    # 운영 DB에서 흔히 켜 두는 로그(잠금 대기, 느린 문장, 연결). 세션 스택 DB에만 겁니다.
    PG_LOGGING = ("log_lock_waits = on", "deadlock_timeout = '1s'", "log_min_duration_statement = 1000",
                  "log_connections = on", "log_disconnections = on")

    def prepare(self) -> None:
        # alter system은 트랜잭션 블록 안에서 못 돌려 문장마다 -c로 나눕니다.
        args = [a for s in self.PG_LOGGING for a in ("-c", f"alter system set {s}")]
        self.docker("exec", self.container("postgres"), "psql", "-U", "iaa", "-d", "erp", *args,
                    "-c", "select pg_reload_conf()")

    def logs(self, service: str, since: str, until: str) -> str:
        """since·until은 RFC 3339. 줄마다 docker가 붙인 시각이 앞에 옵니다."""
        out = self.docker("logs", "--timestamps", "--since", since, "--until", until, self.container(service),
                          check=False)
        return out.stdout + out.stderr

    def audit_lines(self) -> dict[str, str]:
        """감사 볼륨의 JSON Lines 파일 전체(gateway 컨테이너에서 읽음)."""
        out = self.docker("exec", self.container("gateway"), "sh", "-c",
                          "for f in $(find /audit -name '*.jsonl'); do echo \"### $f\"; cat \"$f\"; done", check=False)
        files: dict[str, str] = {}
        name = None
        for line in out.stdout.splitlines():
            if line.startswith("### "):
                name = line[4:].removeprefix("/audit/")
                files[name] = ""
            elif name is not None:
                files[name] += line + "\n"
        return files
