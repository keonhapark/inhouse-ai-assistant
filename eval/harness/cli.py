"""평가 명령.

    uv run python -m harness.cli validate <시나리오 폴더>
    uv run python -m harness.cli run --config <설정.yaml> --scenarios <폴더> --out reports/<이름>
    uv run python -m harness.cli report <실행 결과.json> [-o <보고서.md>]

run은 <이름>.json(회차별 결과)과 <이름>.md(보고서)를 씁니다. 설정 형식은 conditions.example.yaml입니다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
import yaml

from harness.erp import ErpClient
from harness.report import render, summarize
from harness.runner import (CONDITIONS, MAX_RETRIES, HealthCheck, RunRow, _git, count_retries, load_rows_jsonl,
                            load_run, run_matrix, save_run, signature_counts)
from harness.scenario import ScenarioError, has_document_injection, load_scenarios
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


def make_health_check(cfg: dict[str, Any]) -> HealthCheck | None:
    """modelHealth: {urlEnv, path}. 주소는 환경 변수로만 받고 기록에 남기지 않습니다."""
    mh = cfg.get("modelHealth")
    if not mh:
        return None
    base = os.environ.get(mh["urlEnv"])
    if not base:
        raise ValueError(f"modelHealth.urlEnv의 환경 변수 {mh['urlEnv']}가 비어 있습니다")
    url = base.rstrip("/") + mh.get("path", "")

    def check() -> bool:
        try:
            return httpx.get(url, timeout=mh.get("timeoutS", 10)).status_code == 200
        except httpx.HTTPError:
            return False

    return check


def rag_injected_docs(cfg: dict[str, Any]) -> bool | None:
    """rag 컨테이너에 주입 문서 파일(RAG_EXTRA_DOCS)이 켜져 있는지 docker exec로 봅니다. 설정이 없거나 docker를
    부르지 못하면 None(확인 못 함)."""
    import subprocess

    container = cfg.get("rag", {}).get("container")
    if not container:
        return None
    try:
        r = subprocess.run(["docker", "exec", container, "sh", "-c", 'printf %s "$RAG_EXTRA_DOCS"'],
                           capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(r.stdout.strip())


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
    if args.set:
        scenarios = [s for s in scenarios if s["set"] == args.set]
    if args.injected_docs:
        want = args.injected_docs == "only"
        scenarios = [s for s in scenarios if has_document_injection(s) == want]
    injected = rag_injected_docs(cfg)
    if args.injected_docs and injected is not None and injected != (args.injected_docs == "only"):
        raise SystemExit(f"--injected-docs {args.injected_docs}인데 rag의 주입 문서 파일이 "
                         f"{'켜져' if injected else '꺼져'} 있습니다. 스택 설정(RAG_EXTRA_DOCS)을 맞춥니다")
    system, erp = make_factories(cfg)
    out = Path(args.out)
    rows_file = out.with_suffix(".rows.jsonl")
    health = make_health_check(cfg)
    done, started_at, prior_cost = [], None, 0.0
    if args.resume:
        resume = load_rows_jsonl(rows_file)
        done, prior_cost = resume.done, resume.prior_cost_usd
        if out.with_suffix(".json").exists():
            started_at = load_run(out.with_suffix(".json"))[1].started_at
        print(f"이어 돌리기: 끝난 회차 {len(done)}개를 건너뜁니다", flush=True)
        now = (_git("rev-parse", "HEAD"), cfg.get("stackCommit"), cfg.get("packStage"))
        other = {sig: n for sig, n in signature_counts(done).items() if sig != now}
        if other and not args.allow_mixed:
            raise SystemExit(f"앞선 회차가 지금과 다른 (하네스 커밋, 스택 커밋, 팩 단계)에서 돌았습니다: {other}. "
                             f"지금은 {now}입니다. 섞어서 보고하려면 --allow-mixed를 붙입니다(보고서에 커밋별 회차 수가 "
                             "나옵니다)")
    elif rows_file.exists():
        raise SystemExit(f"{rows_file}가 이미 있습니다. 이어 돌리려면 --resume을 붙입니다")
    rows_file.parent.mkdir(parents=True, exist_ok=True)

    def progress(r: RunRow) -> None:
        with rows_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
        print(f"{r.repeat} {r.condition:<15} {r.scenario_id:<40} {r.outcome}", flush=True)

    rows, meta = run_matrix(scenarios, system, erp, conditions=list(cfg["gateway"]["conditions"]),
                            repeats=cfg.get("repeats", 3), base_seed=cfg.get("baseSeed", 0),
                            cost_cap_usd=cfg.get("costCapUsd"), time_limit_s=cfg.get("timeLimitS", 300),
                            model=cfg.get("model"), on_row=progress, done_rows=done,
                            max_runs=args.max_runs, started_at=started_at, health_check=health,
                            prior_cost_usd=prior_cost, pack_stage=cfg.get("packStage"),
                            stack_commit=cfg.get("stackCommit"), injected_docs=injected)
    if not cfg["erp"].get("reset", True):
        meta.notes.append("회차 사이에 erp를 초기화하지 않았습니다(erp.reset: false)")
    if not (cfg["gateway"].get("externalLog") or cfg["gateway"].get("externalLogDocker")):
        meta.notes.append("외부 요청 기록(gateway.externalLog)을 주지 않아 외부 기록의 표지 문자열은 보지 않았습니다")
    meta.notes.extend(cfg.get("notes", []))
    meta.tuned_sets = list(cfg.get("tunedSets", []))
    if injected and any(not has_document_injection(s) for s in scenarios):
        meta.notes.append("주입 문서 파일을 켠 스택에서 문서형 주입이 아닌 시나리오도 돌려, 주입 문서가 그 검색에 섞였을 수 "
                          "있습니다(eval/protocol.md 7절)")
    if injected is None and any(has_document_injection(s) for s in scenarios):
        meta.notes.append("rag 주입 문서 파일이 켜져 있었는지 확인하지 못했습니다(설정 rag.container)")
    meta.retried_runs = count_retries(rows_file)
    if meta.retried_runs:
        meta.notes.append(f"실행 환경 문제(gateway·erp 연결 실패, 재시도 가능한 오류 뒤 모델 서버 응답 없음)로 끝나지 "
                          f"못한 회차를 이어 돌리기로 {meta.retried_runs}번 다시 돌렸습니다(같은 회차 {MAX_RETRIES}번까지). "
                          "다시 돌린 시도의 비용도 비용 합계에 들어 있습니다")
    if health is None and any(r.error and r.error.startswith("재시도 가능한 오류") for r in rows):
        meta.notes.append("modelHealth를 설정하지 않아 재시도 가능한 오류로 끝난 회차는 모두 실패로 셌습니다")
    save_run(rows, meta, out.with_suffix(".json"), summarize(rows, meta))
    out.with_suffix(".md").write_text(render(rows, meta, args.title), encoding="utf-8")
    print(f"{out.with_suffix('.json')}, {out.with_suffix('.md')}")
    return 0 if meta.complete else 2


def cmd_report(args: argparse.Namespace) -> int:
    rows, meta = load_run(Path(args.run))
    if args.update_json:
        save_run(rows, meta, Path(args.run), summarize(rows, meta))
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
    r.add_argument("--set", choices=["dev", "normal", "confirm"], help="이 셋의 시나리오만")
    r.add_argument("--max-runs", type=int, help="이번에 새로 돌릴 회차 수 상한(나눠 돌리기)")
    r.add_argument("--resume", action="store_true", help="<out>.rows.jsonl의 끝난 회차를 건너뛰고 이어 돌림")
    r.add_argument("--injected-docs", choices=["only", "exclude"],
                   help="문서형 주입 시나리오만(only, 주입 파일을 켠 스택) 또는 그 밖의 시나리오만(exclude, 끈 스택)")
    r.add_argument("--allow-mixed", action="store_true",
                   help="앞선 회차와 하네스 커밋·스택 커밋·팩 단계가 달라도 이어 돌림(보고서에 커밋별 회차 수)")
    rep = sub.add_parser("report", help="실행 결과 JSON으로 보고서 다시 만들기")
    rep.add_argument("run")
    rep.add_argument("-o")
    rep.add_argument("--title", default="평가 보고서")
    rep.add_argument("--update-json", action="store_true", help="실행 결과 JSON에 summary를 다시 씀(md와 같은 계산)")
    args = p.parse_args(argv)
    return {"validate": cmd_validate, "run": cmd_run, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
