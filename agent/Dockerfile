# agent 런타임과 MCP 서버. 빌드 문맥은 저장소 루트입니다(packs/와 contracts/의 도구 목록·OpenAPI를 읽음).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /bin/uv
WORKDIR /repo/agent
COPY agent/pyproject.toml agent/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY agent/ ./
RUN uv sync --frozen --no-dev
COPY packs/ /repo/packs/
COPY contracts/mcp/ /repo/contracts/mcp/
COPY contracts/openapi/ /repo/contracts/openapi/
ENV PACK_DIR=/repo/packs/manufacturing \
    CONTRACTS_DIR=/repo/contracts \
    AGENT_AUDIT_LOG=/repo/agent/var/audit.jsonl
EXPOSE 8000 8001
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; [urllib.request.urlopen(f'http://localhost:{p}/health') for p in (8000, 8001)]"
CMD ["uv", "run", "--no-dev", "python", "-m", "agent_runtime.serve"]
