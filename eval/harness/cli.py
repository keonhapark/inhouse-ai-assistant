"""평가 명령.

    uv run python -m harness.cli validate <시나리오 폴더>
    uv run python -m harness.cli run --config <설정.yaml> --scenarios <폴더> --out reports/<이름>
    uv run python -m harness.cli report <실행 결과.json> [-o <보고서.md>]

run은 <이름>.json(회차별 결과)과 <이름>.md(보고서)를 씁니다. 설정 형식은 conditions.example.yaml입니다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

from harness.erp import ErpClient
from harness.report import render
from harness.runner import CONDITIONS, RunRow, load_run, run_matrix, save_run
from harness.scenario import ScenarioError, load_scenarios
from harness.sut import GatewayChat, docker_external_log, jsonl_external_log


def load_config(path: Path) -> dict[str, Any]:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    gw = cfg.get("gateway", {})
    conds = gw.get("conditions") or []
    unknown = [c for c in conds if c not in CONDITIONS]
    if unknown:
        raise ValueError(f"계약에 없는 조건: {unknown}")
    if not conds:
        raise ValueError("gateway.conditions가 비어 있습니다")
    if not gw.get("baseUrl"):
        raise ValueError("gateway.baseUrl이 없습니다")
    if not cfg.get("erp", {}).get("baseUrl"):
        raise ValueError("erp.baseUrl이 없습니다")
    return cfg


def make_factories(cfg: dict[str, Any]):
    """조건은 X-Eval-Condition 헤더로 넘기고(gateway GATEWAY_EVAL_MODE=1), 회차마다 erp를 evalReset으로 되돌립니다."""
    timeout = cfg.get("httpTimeoutS", 120)
    gw = cfg["gateway"]
    external = None
    if gw.get("externalLog"):
        external = jsonl_external_log(Path(gw["externalLog"]))
    elif gw.get("externalLogDocker"):
        d = gw["externalLogDocker"]
        external = docker_external_log(d["container"], d["path"])

    def system(condition: str, seed: int) -> GatewayChat:
        client = httpx.Client(base_url=gw["baseUrl"], timeout=timeout)
        return GatewayChat(client, auditor=gw.get("auditor"), external_log=external, condition=condition)

    erp_cfg = cfg["erp"]

    def erp() -> ErpClient:
        client = ErpClient(httpx.Client(base_url=erp_cfg["baseUrl"], timeout=timeout))
        if erp_cfg.get("reset", True):
            client.reset()
        return client

    return system, erp


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        got = load_scenarios(Path(args.dir))
    except ScenarioError as e:
        print("\n".join(e.problems), file=sys.stderr)
        return 1
    print(f"시나리오 {len(got)}개 통과")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    scenarios = load_scenarios(Path(args.scenarios))
    if args.only:
        wanted = set(args.only.split(","))
        scenarios = [s for s in scenarios if s["id"] in wanted]
    system, erp = make_factories(cfg)

    def progress(r: RunRow) -> None:
        print(f"{r.repeat} {r.condition:<15} {r.scenario_id:<40} {r.outcome}", flush=True)

    rows, meta = run_matrix(scenarios, system, erp, conditions=list(cfg["gateway"]["conditions"]),
                            repeats=cfg.get("repeats", 3), base_seed=cfg.get("baseSeed", 0),
                            cost_cap_usd=cfg.get("costCapUsd"), time_limit_s=cfg.get("timeLimitS", 300),
                            model=cfg.get("model"), on_row=progress)
    if not cfg["erp"].get("reset", True):
        meta.notes.append("회차 사이에 erp를 초기화하지 않았습니다(erp.reset: false)")
    if not (cfg["gateway"].get("externalLog") or cfg["gateway"].get("externalLogDocker")):
        meta.notes.append("외부 요청 기록(gateway.externalLog)을 주지 않아 외부 기록의 표지 문자열은 보지 않았습니다")
    out = Path(args.out)
    save_run(rows, meta, out.with_suffix(".json"))
    out.with_suffix(".md").write_text(render(rows, meta, args.title), encoding="utf-8")
    print(f"{out.with_suffix('.json')}, {out.with_suffix('.md')}")
    return 0 if meta.complete else 2


def cmd_report(args: argparse.Namespace) -> int:
    rows, meta = load_run(Path(args.run))
    text = render(rows, meta, args.title)
    if args.o:
        Path(args.o).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="harness.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="시나리오 폴더 검사")
    v.add_argument("dir")
    r = sub.add_parser("run", help="조건별 실행과 보고서")
    r.add_argument("--config", required=True)
    r.add_argument("--scenarios", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--title", default="평가 보고서")
    r.add_argument("--only", help="쉼표로 나눈 시나리오 ID만(시험 실행용)")
    rep = sub.add_parser("report", help="실행 결과 JSON으로 보고서 다시 만들기")
    rep.add_argument("run")
    rep.add_argument("-o")
    rep.add_argument("--title", default="평가 보고서")
    args = p.parse_args(argv)
    return {"validate": cmd_validate, "run": cmd_run, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
