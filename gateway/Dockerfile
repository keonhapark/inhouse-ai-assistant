# gateway. 빌드 문맥은 저장소 루트입니다(packs/와 contracts/의 등록부·scope 계약을 읽음).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /bin/uv
WORKDIR /repo/gateway
COPY gateway/pyproject.toml gateway/uv.lock ./
RUN uv sync --frozen --no-dev
COPY gateway/gateway ./gateway
COPY gateway/litellm ./litellm
COPY contracts/mcp /repo/contracts/mcp
COPY contracts/auth /repo/contracts/auth
COPY packs/ /repo/packs/
ENV PACK_DIR=/repo/packs/manufacturing CONTRACTS_DIR=/repo/contracts
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uv", "run", "--no-dev", "uvicorn", "--factory", "gateway.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
