# agent 런타임. 빌드 문맥은 저장소 루트입니다(packs/를 읽음).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /bin/uv
WORKDIR /repo/agent
COPY agent/pyproject.toml agent/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY agent/ ./
RUN uv sync --frozen --no-dev
COPY packs/ /repo/packs/
ENV PACK_DIR=/repo/packs/manufacturing \
    AGENT_AUDIT_LOG=/repo/agent/var/audit.jsonl
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uv", "run", "--no-dev", "uvicorn", "--factory", "agent_runtime.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
