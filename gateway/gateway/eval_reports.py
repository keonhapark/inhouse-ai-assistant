"""평가 보고서 조회 `GET /api/eval/reports`, `GET /api/eval/reports/{reportId}`(#332, contracts/openapi/gateway.yaml).

관리자 콘솔 평가 리포트 화면이 읽습니다. 저장소 eval/reports(compose에서 읽기 전용 마운트, `GATEWAY_EVAL_REPORTS_DIR`)의
보고서 JSON(contracts/eval/report.schema.json)을 읽기만 합니다. auditor 역할만 봅니다(위임 토큰 403, 슬랙 토큰 403).

reportId는 계약 pattern만 받고, 실제 파일 경로를 풀어(심볼릭 링크 포함) 폴더 안에 있을 때만 읽습니다. 폴더 밖이면
없는 것과 같이 404입니다.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from gateway.erp_client import ErpClient
from gateway.ops import require_auditor
from gateway.problems import ProblemError

log = logging.getLogger(__name__)

REPORT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")  # contracts/openapi/gateway.yaml getEvalReport reportId


def _inside(folder: Path, path: Path) -> bool:
    try:
        return path.resolve(strict=True).parent == folder.resolve(strict=True)
    except OSError:
        return False


def _load(path: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("meta"), dict) and isinstance(doc.get("rows"), list) \
        else None


def _title(md: Path) -> str | None:
    try:
        for line in md.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip() or None
    except OSError:
        pass
    return None


def summarize(path: Path, doc: dict[str, Any]) -> dict[str, Any]:
    """보고서 본문 meta(snake_case)를 목록 한 줄(EvalReportSummary)로 옮깁니다."""
    meta = doc["meta"]
    sets: list[str] = []
    for row in doc["rows"]:
        s = row.get("set") if isinstance(row, dict) else None
        if isinstance(s, str) and s not in sets:
            sets.append(s)
    out: dict[str, Any] = {
        "reportId": path.stem, "title": _title(path.with_suffix(".md")),
        "startedAt": meta["started_at"], "finishedAt": meta.get("finished_at"), "sets": sets,
        "conditions": list(meta.get("conditions", [])), "packStage": meta.get("pack_stage"),
        "complete": bool(meta.get("complete")), "hasSummary": "summary" in doc,
    }
    for key, src in (("repeats", "repeats"), ("doneRuns", "done_runs"), ("plannedRuns", "planned_runs")):
        if isinstance(meta.get(src), int):
            out[key] = meta[src]
    return out


def build_router(erp: ErpClient, folder: Path) -> APIRouter:
    api = APIRouter()

    @api.get("/eval/reports")
    async def list_reports(request: Request) -> JSONResponse:
        await require_auditor(erp, request)
        items = []
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            if not REPORT_ID.fullmatch(path.stem) or not _inside(folder, path):
                continue
            doc = _load(path)
            if doc is None or not isinstance(doc["meta"].get("started_at"), str):
                log.warning("평가 보고서를 읽지 못해 목록에서 뺍니다: %s", path.name)
                continue
            items.append(summarize(path, doc))
        items.sort(key=lambda i: i["startedAt"], reverse=True)
        return JSONResponse({"items": items})

    @api.get("/eval/reports/{report_id}")
    async def get_report(request: Request, report_id: str) -> JSONResponse:
        await require_auditor(erp, request)
        path = folder / f"{report_id}.json"
        doc = _load(path) if REPORT_ID.fullmatch(report_id) and _inside(folder, path) else None
        if doc is None:
            raise ProblemError(404, "not-found", "없는 평가 보고서입니다")
        return JSONResponse(doc)

    return api
