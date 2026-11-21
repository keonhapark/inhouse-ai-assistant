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
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
import yaml

from harness.erp import ErpClient
from harness.paths import EVAL_DIR, ROOT
from harness.report import render, summarize
from harness.runner import (MAX_RETRIES, RUN_CONDITIONS, HealthCheck, RunRow, _git, count_retries, load_rows_jsonl,
                            load_run, run_matrix, save_run, signature_counts, system_condition)
from harness.scenario import ScenarioError, has_document_injection, load_scenarios
from harness.sut import GatewayChat, docker_external_log, jsonl_external_log


# contracts/openapi/gateway.yaml createConversation의 X-Eval-Model-Override
MODEL_OVERRIDES = ("local=local-exaone", "external=external-sonnet", "local=local-exaone,external=external-sonnet")


def load_config(path: Path) -> dict[str, Any]:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    gw = cfg.get("gateway", {})
    conds = gw.get("conditions") or []
    unknown = [c for c in conds if c not in RUN_CONDITIONS]
    if unknown:
        raise ValueError(f"계약에 없는 조건: {unknown}")
    if not conds:
        raise ValueError("gateway.conditions가 비어 있습니다")
    if gw.get("modelOverride") not in (None, *MODEL_OVERRIDES):
        raise ValueError(f"계약에 없는 모델 교체 값: {gw['modelOverride']} (가능: {', '.join(MODEL_OVERRIDES)})")
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
        return GatewayChat(client, auditor=gw.get("auditor"), external_log=external,
                           condition=system_condition(condition), model_override=gw.get("modelOverride"))

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


def rag_file_sha256(cfg: dict[str, Any], env: str) -> str | None:
    """rag 컨테이너의 환경 변수 env가 가리키는 파일의 SHA-256을 docker exec로 구합니다. 변수가 비었거나 docker를
    부르지 못하면 None."""
    import subprocess

    container = cfg.get("rag", {}).get("container")
    if not container:
        return None
    try:
        r = subprocess.run(["docker", "exec", container, "sh", "-c", f'f="${env}"; [ -z "$f" ] || sha256sum "$f"'],
                           capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    got = r.stdout.split()
    return got[0] if got and re.fullmatch(r"[0-9a-f]{64}", got[0]) else None


def verify_stack(cfg: dict[str, Any], required: bool) -> str | None:
    """설정 stackCheck.containers가 있으면 띄운 스택이 stackCommit의 소스인지 봅니다(#449). 다르면 멈춥니다.
    required(확인 셋)인데 설정이 없으면 멈춥니다."""
    from harness.stackcheck import StackCheckError, check_stack

    containers = cfg.get("stackCheck", {}).get("containers")
    commit = cfg.get("stackCommit")
    if not containers or not commit:
        if required:
            raise SystemExit("--bundle 실행은 띄운 스택을 확인합니다. 설정에 stackCommit과 stackCheck.containers를 둡니다")
        return None
    try:
        c = check_stack(list(containers), commit)
    except StackCheckError as e:
        raise SystemExit(str(e)) from e
    if not c.ok:
        raise SystemExit(f"띄운 스택이 stackCommit과 다릅니다: {c.describe()}. 예: {', '.join(c.mismatched[:5])}")
    print(c.describe(), flush=True)
    return c.describe()


def check_bundle_scenarios(bundle: Path, scenarios: Path) -> None:
    """--bundle일 때 실제로 읽는 시나리오 파일이 모두 대조한 묶음의 manifest에 있는지 봅니다(#432). 내용 해시는
    check_bundle이 이미 manifest와 대조했습니다."""
    from harness.bundle import unlisted
    from harness.scenario import scenario_paths

    paths = scenario_paths(scenarios)
    if not paths:
        raise SystemExit(f"--scenarios {scenarios}에 시나리오 파일이 없습니다")
    bad = unlisted(bundle, paths)
    if bad:
        raise SystemExit(f"--bundle을 주면 시나리오는 묶음 manifest의 파일에서만 읽습니다. manifest에 없는 파일 "
                         f"{len(bad)}개: {', '.join(bad[:5])}")


def check_bundle_injected_docs(bundle: Path, cfg: dict[str, Any]) -> None:
    """rag가 읽는 주입 문서 파일(RAG_EXTRA_DOCS)의 해시가 묶음 manifest 파일 중 하나와 같은지 봅니다(#432)."""
    from harness.bundle import manifest_sha256s

    sha = rag_file_sha256(cfg, "RAG_EXTRA_DOCS")
    if sha is None:
        raise SystemExit("rag의 주입 문서 파일 해시를 구하지 못했습니다(rag.container, docker exec)")
    if sha not in manifest_sha256s(bundle):
        raise SystemExit(f"rag가 읽는 주입 문서 파일({sha[:12]})이 묶음 manifest의 어느 파일과도 해시가 다릅니다")


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        got = load_scenarios(Path(args.dir))
    except ScenarioError as e:
        print("\n".join(e.problems), file=sys.stderr)
        return 1
    print(f"시나리오 {len(got)}개 통과")
    return 0


def check_bundle(path: str, name: str | None = None) -> str:
    """묶음 해시가 계약 표와 맞는지 보고, 맞지 않으면 멈춥니다. 맞으면 보고서에 적을 한 줄을 돌려줍니다."""
    from harness.bundle import BundleError, check, describe

    try:
        c = check(Path(path), name)
    except (BundleError, OSError, KeyError, ValueError) as e:
        raise SystemExit(f"묶음을 읽지 못했습니다: {e}") from e
    if not c.ok:
        raise SystemExit(f"묶음 해시가 계약과 맞지 않습니다: {describe(c)}"
                         + (f". 다른 파일: {', '.join(c.mismatched_files[:5])}" if c.mismatched_files else ""))
    return describe(c)


def cmd_bundle_check(args: argparse.Namespace) -> int:
    print(check_bundle(args.dir, args.name))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    bundle = check_bundle(args.bundle, args.bundle_name) if args.bundle else None
    if args.bundle:
        check_bundle_scenarios(Path(args.bundle), Path(args.scenarios))
    scenarios = load_scenarios(Path(args.scenarios))
    if args.bundle:
        with_files = [s["id"] for s in scenarios
                      if any(isinstance(t, dict) and t.get("attachments") for t in s.get("turns", []))]
        if with_files:
            raise SystemExit("--bundle 실행은 아직 시나리오 첨부 파일을 묶음에서 읽거나 대조하지 않습니다. 첨부가 있는 "
                             f"시나리오 {len(with_files)}개: {', '.join(with_files[:5])}")
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
    if args.bundle and injected is None:
        raise SystemExit("--bundle이면 rag의 주입 문서 파일을 확인해야 합니다. 설정에 rag.container를 두고 docker를 "
                         "부를 수 있게 합니다")
    if args.bundle and injected:
        check_bundle_injected_docs(Path(args.bundle), cfg)
    stack_check = verify_stack(cfg, required=bool(args.bundle))
    system, erp = make_factories(cfg)
    out = Path(args.out)
    rows_file = out.with_suffix(".rows.jsonl")
    health = make_health_check(cfg)
    done, started_at, prior_cost = [], None, 0.0
    if args.resume:
        resume = load_rows_jsonl(rows_file)
        done, prior_cost = resume.done, resume.prior_cost_usd
        if out.with_suffix(".json").exists():
            prior_meta = load_run(out.with_suffix(".json"))[1]
            started_at = prior_meta.started_at
            if prior_meta.bundle != bundle:
                raise SystemExit(f"앞선 회차의 묶음({prior_meta.bundle})이 지금 묶음({bundle})과 다릅니다")
            if prior_meta.model_override != cfg["gateway"].get("modelOverride"):
                raise SystemExit(f"앞선 회차의 모델 교체 값({prior_meta.model_override})이 지금 설정"
                                 f"({cfg['gateway'].get('modelOverride')})과 다릅니다. 다른 출력 이름으로 돌립니다")
        other_bundles = {r.bundle for r in done} - {bundle}
        if other_bundles:
            raise SystemExit(f"앞선 회차 중 지금 묶음({bundle})과 다른 묶음에서 돈 회차가 있습니다: "
                             f"{sorted(map(str, other_bundles))}. 다른 출력 이름으로 돌립니다")
        print(f"이어 돌리기: 끝난 회차 {len(done)}개를 건너뜁니다", flush=True)
        now = (_git("rev-parse", "HEAD"), cfg.get("stackCommit"), cfg.get("packStage"))
        other = {sig: n for sig, n in signature_counts(done).items() if sig != now}
        moved = {sig: n for sig, n in other.items() if sig[1:] != now[1:]}
        if bundle and moved:
            raise SystemExit(f"확인 셋(--bundle)을 이어 돌릴 때는 스택 커밋과 팩 단계가 앞선 회차와 같아야 합니다"
                             f"(--allow-mixed여도). 다른 회차: {moved}, 지금: {now}. 하네스 커밋 차이만 허용합니다")
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
                            stack_commit=cfg.get("stackCommit"), injected_docs=injected, bundle=bundle)
    if not cfg["erp"].get("reset", True):
        meta.notes.append("회차 사이에 erp를 초기화하지 않았습니다(erp.reset: false)")
    if not (cfg["gateway"].get("externalLog") or cfg["gateway"].get("externalLogDocker")):
        meta.notes.append("외부 요청 기록(gateway.externalLog)을 주지 않아 외부 기록의 표지 문자열은 보지 않았습니다")
    meta.notes.extend(cfg.get("notes", []))
    meta.tuned_sets = list(cfg.get("tunedSets", []))
    meta.model_override = cfg["gateway"].get("modelOverride")
    meta.bundle = bundle
    meta.stack_check = stack_check
    meta.model_settings = {str(k): str(v) for k, v in (cfg.get("modelSettings") or {}).items()}
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


DEV_TOOLCALL = ROOT / "agent/eval_dev/tool_calls.jsonl"


def _toolcall_items(args: argparse.Namespace) -> list[dict[str, Any]]:
    from harness.toolcall import ToolcallError, load_items, tool_catalog

    try:
        items = load_items(Path(args.items))
    except ToolcallError as e:
        raise SystemExit("\n".join(e.problems)) from None
    if getattr(args, "max_stage", None):
        items = [i for i in items if tool_catalog()[i["targetTool"]]["stage"] <= args.max_stage]
    return items


def cmd_toolcall_validate(args: argparse.Namespace) -> int:
    print(f"항목 {len(_toolcall_items(args))}개 통과")
    return 0


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_toolcall_run(args: argparse.Namespace) -> int:
    """agent POST /eval/tool-call로 항목을 부르고 채점합니다(AGENT_EVAL_MODE=1인 agent)."""
    import platform

    from harness import toolcall_report
    from harness.runner import _git, _now
    from harness.setup import run_setup
    from harness.toolcall import run_items

    bundle = None
    if args.bundle:
        from harness.bundle import unlisted

        bundle = check_bundle(args.bundle, args.bundle_name)
        bad = unlisted(Path(args.bundle), [Path(args.items)])
        if bad:
            raise SystemExit(f"--bundle을 주면 --items는 묶음 manifest의 파일이어야 합니다: {bad[0]}")
    items = _toolcall_items(args)
    variant = json.loads(args.variant)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows_file = out.with_suffix(".rows.jsonl")
    if rows_file.exists():
        raise SystemExit(f"{rows_file}가 이미 있습니다")
    meta = {"title": args.title, "commit": _git("rev-parse", "HEAD"),
            "dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
            "machine": f"{platform.platform()} {platform.machine()}", "started_at": _now(), "items": args.items,
            "itemsSha256": _sha256(Path(args.items)), "itemCount": len(items), "maxStage": args.max_stage,
            "model": args.model, "variant": variant, "repeats": args.repeats, "notes": list(args.note or [])}
    if bundle:
        # 저장소 밖 묶음의 절대 경로는 보고서에 남기지 않고 묶음 안 경로만 적습니다
        meta["items"] = str(Path(args.items).resolve().relative_to(Path(args.bundle).resolve()))
        meta["bundle"] = bundle
    client = httpx.Client(base_url=args.agent_url, timeout=args.timeout)
    setup = None
    if args.erp_url:
        erp = ErpClient(httpx.Client(base_url=args.erp_url, timeout=args.timeout))

        def setup(item: dict[str, Any]) -> dict[str, str]:
            if args.erp_reset:
                erp.reset()
            return run_setup(item, erp)

    def post(body: dict[str, Any]) -> tuple[int, Any]:
        r = client.post("/eval/tool-call", json=body)
        return r.status_code, (r.json() if r.status_code == 200 else r.text[:300])

    def progress(row: dict[str, Any]) -> None:
        with rows_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{row['repeat']} {row['id']} {row['outcome']}", flush=True)

    rows = run_items(items, post, variant=variant, model=args.model, repeats=args.repeats, setup=setup,
                     on_row=progress)
    meta["finished_at"] = _now()
    summary = toolcall_report.summarize(rows, args.repeats)
    out.with_suffix(".json").write_text(json.dumps({"meta": meta, "summary": summary, "rows": rows},
                                                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    out.with_suffix(".md").write_text(toolcall_report.render(rows, meta, args.title), encoding="utf-8")
    print(f"{out.with_suffix('.json')}, {out.with_suffix('.md')}")
    return 0


def cmd_toolcall_report(args: argparse.Namespace) -> int:
    """기록(.json)을 지금 채점 규칙으로 다시 채점하고 보고서를 다시 씁니다."""
    from harness import toolcall_report
    from harness.toolcall import rescore

    data = json.loads(Path(args.run).read_text(encoding="utf-8"))
    items = _toolcall_items(args)
    rows = rescore(items, data["rows"])
    meta = data["meta"]
    data["rows"], data["summary"] = rows, toolcall_report.summarize(rows, meta.get("repeats", 1))
    Path(args.run).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    Path(args.run).with_suffix(".md").write_text(toolcall_report.render(rows, meta, meta.get("title", "도구 호출 측정")),
                                                 encoding="utf-8")
    return 0


def cmd_vision_run(args: argparse.Namespace) -> int:
    """이미지 읽기 측정: 그림마다 gateway 대화를 열어 같은 질문과 함께 붙이고 답을 채점합니다(#110, #386)."""
    from harness import vision

    truths = vision.load_truth(Path(args.truth))
    if args.kind:
        truths = [t for t in truths if t["kind"] == args.kind]

    def system() -> GatewayChat:
        return GatewayChat(httpx.Client(base_url=args.gateway_url, timeout=args.timeout), auditor=None,
                           condition=args.condition)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = vision.run_items(truths, system, on_row=lambda r: print(r["id"], r["allCorrect"], r["error"] or "",
                                                                    flush=True))
    data = {"meta": {"truth": args.truth, "condition": args.condition, "notes": list(args.note or [])},
            "summary": vision.summarize(rows), "rows": rows}
    out.with_suffix(".json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(data["summary"], ensure_ascii=False))
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
    r.add_argument("--bundle", help="확인 셋 묶음 폴더(manifest 포함). 해시가 contracts/eval/confirm-sets.md와 다르면 멈춤")
    r.add_argument("--bundle-name", help="계약 표의 묶음 이름(manifest에 name이 없을 때)")
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
    tv = sub.add_parser("toolcall-validate", help="도구 호출 항목(toolcall-v1) 검사")
    tv.add_argument("--items", default=str(DEV_TOOLCALL))
    tv.add_argument("--max-stage", type=int)
    tr = sub.add_parser("toolcall-run", help="agent /eval/tool-call로 도구 호출 측정")
    tr.add_argument("--items", default=str(DEV_TOOLCALL))
    tr.add_argument("--agent-url", required=True)
    tr.add_argument("--out", required=True)
    tr.add_argument("--model", help="gateway 출구 별칭(local, external 등). 없으면 에이전트 정책")
    tr.add_argument("--variant", default="{}", help='측정 단계 장치(JSON, 예 {"thinking": false})')
    tr.add_argument("--repeats", type=int, default=1)
    tr.add_argument("--max-stage", type=int, help="이 단계까지의 targetTool만(1단계는 1)")
    tr.add_argument("--erp-url", help="setup이 있는 항목용 erp 주소")
    tr.add_argument("--erp-reset", action="store_true", help="setup 전에 erp를 초기화(ERP_EVAL_RESET=1)")
    tr.add_argument("--timeout", type=float, default=300)
    tr.add_argument("--title", default="도구 호출 측정")
    tr.add_argument("--note", action="append", help="보고서 실행 정보에 적을 말(기기, 모델 digest, Ollama 판 등)")
    tr.add_argument("--bundle", help="확인 묶음 폴더(toolcall-v1). 해시를 계약 표와 대조하고 --items가 그 manifest 파일인지 봄")
    tr.add_argument("--bundle-name", help="계약 표의 묶음 이름(manifest에 이름이 없을 때)")
    tp = sub.add_parser("toolcall-report", help="도구 호출 기록을 지금 규칙으로 다시 채점")
    tp.add_argument("run")
    tp.add_argument("--items", default=str(DEV_TOOLCALL))
    bc = sub.add_parser("bundle-check", help="확인 셋 묶음 해시를 계약 표(contracts/eval/confirm-sets.md)와 대조")
    bc.add_argument("dir")
    bc.add_argument("--name", help="계약 표의 묶음 이름(manifest에 name이 없을 때)")
    vr = sub.add_parser("vision-run", help="이미지 읽기 측정(도면·불량 사진, images/truth.jsonl)")
    vr.add_argument("--gateway-url", required=True)
    vr.add_argument("--out", required=True)
    vr.add_argument("--truth", default=str(EVAL_DIR / "images/truth.jsonl"))
    vr.add_argument("--kind", choices=["drawing", "defect"])
    vr.add_argument("--condition", default="full")
    vr.add_argument("--timeout", type=float, default=300)
    vr.add_argument("--note", action="append")
    args = p.parse_args(argv)
    return {"validate": cmd_validate, "run": cmd_run, "report": cmd_report, "toolcall-validate": cmd_toolcall_validate,
            "toolcall-run": cmd_toolcall_run, "toolcall-report": cmd_toolcall_report,
            "vision-run": cmd_vision_run, "bundle-check": cmd_bundle_check}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
