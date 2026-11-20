"""저장소 안의 계약 파일 경로."""

from __future__ import annotations

from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
ROOT = EVAL_DIR.parent
CONTRACTS = ROOT / "contracts"
SCENARIO_SCHEMA = CONTRACTS / "eval/scenario.schema.json"
ERP_OPENAPI = CONTRACTS / "openapi/erp.yaml"
MCP_TOOLS = CONTRACTS / "mcp/tools.json"
