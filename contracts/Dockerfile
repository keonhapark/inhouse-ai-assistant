# 상태 있는 가짜 erp. 빌드 문맥은 저장소 루트입니다(packs/를 읽음).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /bin/uv
WORKDIR /repo/contracts
COPY contracts/pyproject.toml contracts/uv.lock ./
RUN uv sync --frozen --no-dev
COPY contracts/ ./
COPY packs/ /repo/packs/
ENV PACK_DIR=/repo/packs/manufacturing
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "fakes.erp.app:app", "--host", "0.0.0.0", "--port", "8000"]
