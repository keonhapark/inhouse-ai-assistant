# rag. 빌드 문맥은 저장소 루트입니다(packs/의 문서 목록과 조직을 읽음).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /bin/uv
WORKDIR /repo/rag
COPY rag/pyproject.toml rag/uv.lock ./
RUN uv sync --frozen --no-dev
COPY rag/rag ./rag
COPY rag/corpus ./corpus
COPY rag/templates ./templates
COPY packs/ /repo/packs/
COPY contracts/eval /repo/contracts/eval
ENV PACK_DIR=/repo/packs/manufacturing RAG_CACHE_DIR=/data/rag-cache
EXPOSE 8000
# 시작 때 gateway를 기다리고(최대 120초) 문서를 임베딩하므로 시작 유예를 둡니다(#127).
HEALTHCHECK --interval=5s --timeout=3s --start-period=180s --retries=3 CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uv", "run", "--no-dev", "uvicorn", "--factory", "rag.app:from_env", "--host", "0.0.0.0", "--port", "8000"]
