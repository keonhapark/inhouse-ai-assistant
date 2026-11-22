"""장애를 주입하고 묶음을 만듭니다.

    cd incident && uv run python -m incident.run --session 1 --faults all --repeat 3

세션 스택(iaa-s<번호>, --profile full)이 떠 있어야 합니다(--up이면 띄움). 묶음은 data/runs/<runId>/<incidentId>/에
truth.json(정답), logs/, audit/, traffic.jsonl(사용자 쪽 증상)로 남습니다.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from incident import faults as F
from incident.collect import collect, service_logs
from incident.stack import ROOT, Stack
from incident.tickets import file_ticket, pick
from incident.traffic import KST, Traffic, dumps

DATA = Path(__file__).resolve().parents[1] / "data" / "runs"
PACK = ROOT / "packs" / "manufacturing"


def dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def employees() -> list[dict[str, Any]]:
    return json.loads((PACK / "fixtures" / "employees.json").read_text(encoding="utf-8"))["employees"]


def run_one(stack: Stack, fault: F.Fault, run_dir: Path, n: int, rng: random.Random, password: str,
            baseline_s: int, post_s: int) -> dict[str, Any]:
    staff = [e for e in employees() if e["grade"] == "staff" and e["unit_id"] != "it-ops"]
    user = staff[0]
    reporter = rng.choice(staff)
    auditor = next(e for e in employees() if e["unit_id"] == "it-ops")
    incident_id = f"{fault.id}-{n:02d}"
    out = run_dir / incident_id
    out.mkdir(parents=True, exist_ok=True)
    gateway = f"http://localhost:{8000 + 100 * stack.session + 10}"

    traffic = Traffic(stack.erp_url, gateway, user["employee_no"], password)
    start = datetime.now(KST)
    events = stack.watch_events()
    traffic.start()
    time.sleep(baseline_s)
    injected = datetime.now(KST)
    injection = fault.inject(stack, fault.duration_s)
    time.sleep(fault.duration_s)
    recover_started = datetime.now(KST)
    before_recovery = service_logs(stack, start, recover_started)
    fault.recover(stack)
    recovered = datetime.now(KST)
    time.sleep(post_s)
    records = traffic.stop()
    end = datetime.now(KST)
    container_events = Stack.stop_events(events)

    title, description = pick(fault.id, rng)
    ticket = file_ticket(stack.erp_url, reporter["employee_no"], password, title, description)
    counts = collect(stack, out, start, end, auditor["employee_no"], password, before_recovery, recover_started)
    (out / "traffic.jsonl").write_text(dumps(records), encoding="utf-8")
    (out / "logs" / "docker-events.log").write_text(container_events, encoding="utf-8")
    counts["logs/docker-events.log"] = container_events.count("\n")
    truth = {
        "incidentId": incident_id, "runId": run_dir.name, "fault": fault.id, "title": fault.title,
        "rootService": fault.root_service, "kind": fault.kind,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "injectedAt": injected.isoformat(), "recoverStartedAt": recover_started.isoformat(),
        "recoveredAt": recovered.isoformat(),
        "ticket": {"id": ticket["id"], "requesterId": ticket["requesterId"], "title": title,
                   "description": description, "createdAt": ticket["createdAt"]},
        "files": counts,
        "trafficErrors": sum(1 for r in records if r["error"] or (r["status"] or 0) >= 500),
        "trafficTotal": len(records),
    }
    if injection:
        truth["injection"] = injection
    (out / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return truth


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", type=int, default=1)
    ap.add_argument("--faults", default="all", help="쉼표로 구분한 장애 ID 또는 all")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--baseline", type=int, default=45, help="주입 전 평소 구간(초)")
    ap.add_argument("--post", type=int, default=30, help="복구 뒤 구간(초)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--up", action="store_true", help="세션 스택을 먼저 띄웁니다")
    args = ap.parse_args(argv)

    stack = Stack(args.session)
    env = dotenv(stack.env_file)
    password = os.environ.get("ERP_DEMO_PASSWORD") or env.get("ERP_DEMO_PASSWORD") or "demo"
    if args.up:
        stack.up()
    stack.prepare()
    chosen = F.CATALOG if args.faults == "all" else tuple(F.by_id(x) for x in args.faults.split(","))
    run_dir = DATA / datetime.now(KST).strftime("%Y%m%d-%H%M")
    rng = random.Random(args.seed)
    for n in range(1, args.repeat + 1):
        for fault in chosen:
            t = run_one(stack, fault, run_dir, n, rng, password, args.baseline, args.post)
            print(f"{t['incidentId']}: 요청 {t['trafficTotal']}건 중 실패 {t['trafficErrors']}건, 티켓 {t['ticket']['id']}",
                  flush=True)
    print(f"묶음: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
