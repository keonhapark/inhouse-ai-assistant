"""erp 동시 예약·동시 결재 부하 시험.

실행(저장소 루트에서, erp가 떠 있어야 함):
    bash erp/ci/start.sh            # 또는 ERP_PORT=8140 ERP_PG_PORT=8160 bash erp/ci/start.sh
    cd contracts && uv run python ../erp/bench/load.py --base http://localhost:8040/api/v1 \
        --concurrency 50 --rounds 20 --out ../erp/bench/results/<이름>.json

시나리오 네 가지를 차례로 돌립니다.
- room_contention: 같은 회의실·같은 시간대에 동시 예약 C건을 라운드마다 보냅니다. 라운드마다 201이 정확히 1건,
  나머지는 409 room-conflict, 5xx는 0건이어야 합니다.
- room_throughput: 일꾼 C개가 서로 겹치지 않는 시간대를 예약합니다. 처리량과 지연을 봅니다.
- approval_contention: 지출 결재 문서를 하나 올린 뒤 결재자가 같은 version으로 동시 승인 C건을 보냅니다.
  라운드마다 201이 정확히 1건, 나머지는 409(version-conflict 또는 invalid-state)여야 합니다.
- approval_throughput: 문서 C×rounds개를 미리 올리고 서로 다른 문서를 동시에 승인합니다.

시나리오마다 상태 코드·문제 코드 분포, 지연 p50/p95/p99/최대, 처리량(요청/초), 규칙 위반 수를 냅니다.
같은 erp에 다시 돌려도 겹치지 않게 회의실 날짜는 실행마다 무작위로 멀리 잡습니다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import random
import statistics
import time
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[2]


class Client:
    def __init__(self, base: str, password: str, concurrency: int) -> None:
        limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency * 2)
        self.http = httpx.AsyncClient(base_url=base, timeout=60, limits=limits)
        self.password = password
        self.tokens: dict[str, str] = {}

    async def token(self, emp: str) -> str:
        if emp not in self.tokens:
            r = await self.http.post("/auth/login", json={"employeeNo": emp, "password": self.password})
            r.raise_for_status()
            self.tokens[emp] = r.json()["accessToken"]
        return self.tokens[emp]

    async def call(self, method: str, path: str, emp: str, body: dict | None = None) -> tuple[int, str, float, dict]:
        headers = {"Authorization": f"Bearer {await self.token(emp)}"}
        if method == "POST":
            headers["Idempotency-Key"] = uuid.uuid4().hex
        t = time.perf_counter()
        r = await self.http.request(method, path, headers=headers, json=body)
        ms = (time.perf_counter() - t) * 1000
        data = r.json() if r.content else {}
        code = data.get("type", "").removeprefix("urn:problem:") if r.status_code >= 400 else ""
        return r.status_code, code, ms, data


def summary(name: str, results: list[tuple[int, str, float]], seconds: float, violations: int, notes: str) -> dict:
    lat = sorted(ms for _, _, ms in results)
    q = statistics.quantiles(lat, n=100, method="inclusive") if len(lat) >= 2 else lat * 99
    return {
        "scenario": name,
        "requests": len(results),
        "seconds": round(seconds, 2),
        "throughput_rps": round(len(results) / seconds, 1) if seconds else None,
        "status": dict(sorted(Counter(str(s) for s, _, _ in results).items())),
        "problems": dict(sorted(Counter(c for _, c, _ in results if c).items())),
        "server_errors": sum(1 for s, _, _ in results if s >= 500),
        "latency_ms": {"p50": round(q[49], 1), "p95": round(q[94], 1), "p99": round(q[98], 1),
                       "max": round(lat[-1], 1)},
        "violations": violations,
        "notes": notes,
    }


def load_staff() -> tuple[list[str], dict[str, str]]:
    """팩 고정 데이터에서 팀원 목록과 팀원 → 팀장을 읽습니다."""
    emps = json.loads((ROOT / "packs/manufacturing/fixtures/employees.json").read_text(encoding="utf-8"))["employees"]
    leaders = {e["unit_id"]: e["id"] for e in emps if e["grade"] == "team_leader"}
    staff = [e["id"] for e in emps if e["grade"] == "staff" and e["unit_id"] in leaders]
    return staff, {e["id"]: leaders[e["unit_id"]] for e in emps if e["id"] in staff}


def slot(day: date, index: int) -> tuple[str, str]:
    """하루 9시~17시 30분 단위 슬롯(16개)."""
    start = datetime(day.year, day.month, day.day, 9, 0, tzinfo=KST) + timedelta(minutes=30 * index)
    return start.isoformat(), (start + timedelta(minutes=30)).isoformat()


async def room_contention(c: Client, staff: list[str], rooms: list[str], conc: int, rounds: int, base_day: date):
    results, violations = [], 0
    t0 = time.perf_counter()
    for r in range(rounds):
        s, e = slot(base_day + timedelta(days=r // 16), r % 16)
        room = rooms[r % len(rooms)]
        batch = await asyncio.gather(*[c.call("POST", "/room-reservations", staff[i % len(staff)],
                                              {"roomId": room, "startsAt": s, "endsAt": e, "title": "부하"})
                                       for i in range(conc)])
        ok = sum(1 for st, _, _, _ in batch if st == 201)
        bad = sum(1 for st, code, _, _ in batch if st != 201 and code != "room-conflict")
        violations += (ok != 1) + bad
        results += [(st, code, ms) for st, code, ms, _ in batch]
    return summary("room_contention", results, time.perf_counter() - t0, violations,
                   f"라운드 {rounds}번 × 같은 회의실·시간대 동시 {conc}건. 위반 = 201이 1건이 아닌 라운드 + room-conflict가 아닌 실패")


async def room_throughput(c: Client, staff: list[str], rooms: list[str], conc: int, rounds: int, base_day: date):
    # 일꾼마다 (회의실, 날짜)를 따로 갖고 그날 슬롯을 차례로 예약합니다.
    async def worker(w: int) -> list[tuple[int, str, float]]:
        out = []
        room = rooms[w % len(rooms)]
        day = base_day + timedelta(days=w // len(rooms))
        for i in range(rounds):
            s, e = slot(day + timedelta(days=(i // 16) * 1000), i % 16)
            st, code, ms, _ = await c.call("POST", "/room-reservations", staff[w % len(staff)],
                                           {"roomId": room, "startsAt": s, "endsAt": e, "title": "부하"})
            out.append((st, code, ms))
        return out

    t0 = time.perf_counter()
    batches = await asyncio.gather(*[worker(w) for w in range(conc)])
    results = [x for b in batches for x in b]
    violations = sum(1 for st, _, _ in results if st != 201)
    return summary("room_throughput", results, time.perf_counter() - t0, violations,
                   f"일꾼 {conc}개 × 겹치지 않는 예약 {rounds}건. 위반 = 201이 아닌 응답")


async def new_expense(c: Client, emp: str) -> dict:
    st, _, _, data = await c.call("POST", "/approval-documents", emp, {"formId": "expense", "fields": {
        "amount": 10_000, "spent_on": "2026-11-02", "merchant": "부하상회", "purpose": "부하 시험"}})
    if st != 201:
        raise RuntimeError(f"상신 실패 {st} {data}")
    return data["resource"]


async def approval_contention(c: Client, staff: list[str], leader_of: dict[str, str], conc: int, rounds: int):
    results, violations = [], 0
    t0 = time.perf_counter()
    for r in range(rounds):
        emp = staff[r % len(staff)]
        doc = await new_expense(c, emp)
        approver = leader_of[emp]
        path = f"/approval-documents/{doc['id']}/approve"
        batch = await asyncio.gather(*[c.call("POST", path, approver, {"version": doc["version"]})
                                       for _ in range(conc)])
        ok = sum(1 for st, _, _, _ in batch if st == 201)
        bad = sum(1 for st, code, _, _ in batch
                  if st != 201 and not (st == 409 and code in ("version-conflict", "invalid-state")))
        violations += (ok != 1) + bad
        results += [(st, code, ms) for st, code, ms, _ in batch]
    return summary("approval_contention", results, time.perf_counter() - t0, violations,
                   f"라운드 {rounds}번 × 같은 문서·같은 version 동시 승인 {conc}건(상신 시간 포함하지 않은 지연, 처리량은 상신 포함 경과 시간 기준). "
                   "위반 = 201이 1건이 아닌 라운드 + 409 version-conflict/invalid-state가 아닌 실패")


async def approval_throughput(c: Client, staff: list[str], leader_of: dict[str, str], conc: int, rounds: int):
    docs = []
    for chunk in range(0, conc * rounds, conc):
        emps = [staff[(chunk + i) % len(staff)] for i in range(conc)]
        docs += [(leader_of[e], d) for e, d in zip(emps, await asyncio.gather(*[new_expense(c, e) for e in emps]))]
    queue: asyncio.Queue = asyncio.Queue()
    for d in docs:
        queue.put_nowait(d)

    async def worker() -> list[tuple[int, str, float]]:
        out = []
        while not queue.empty():
            approver, doc = queue.get_nowait()
            st, code, ms, _ = await c.call("POST", f"/approval-documents/{doc['id']}/approve", approver,
                                           {"version": doc["version"]})
            out.append((st, code, ms))
        return out

    t0 = time.perf_counter()
    batches = await asyncio.gather(*[worker() for _ in range(conc)])
    results = [x for b in batches for x in b]
    violations = sum(1 for st, _, _ in results if st != 201)
    return summary("approval_throughput", results, time.perf_counter() - t0, violations,
                   f"서로 다른 문서 {len(docs)}개를 일꾼 {conc}개가 동시에 승인. 위반 = 201이 아닌 응답")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("ERP_BASE_URL", "http://localhost:8040/api/v1"))
    ap.add_argument("--password", default=os.environ.get("ERP_DEMO_PASSWORD", "demo"))
    ap.add_argument("--concurrency", type=int, default=50)
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--seed", type=int, default=None, help="회의실 날짜를 고르는 난수 씨앗(기본: 무작위)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    staff, leader_of = load_staff()
    c = Client(a.base, a.password, a.concurrency)
    rooms = [r["id"] for r in (await c.http.get("/rooms", headers={
        "Authorization": f"Bearer {await c.token(staff[0])}"})).json()["items"]]
    await asyncio.gather(*[c.token(e) for e in set(staff) | set(leader_of.values())])
    rnd = random.Random(a.seed)
    base_day = date.today() + timedelta(days=rnd.randint(2_000, 200_000))

    report = {
        "measuredAt": datetime.now(KST).isoformat(timespec="seconds"),
        "machine": f"{platform.machine()} {platform.system()} {platform.release()}",
        "base": a.base, "concurrency": a.concurrency, "rounds": a.rounds,
        "scenarios": [
            await room_contention(c, staff, rooms, a.concurrency, a.rounds, base_day),
            await room_throughput(c, staff, rooms, a.concurrency, a.rounds, base_day + timedelta(days=100)),
            await approval_contention(c, staff, leader_of, a.concurrency, a.rounds),
            await approval_throughput(c, staff, leader_of, a.concurrency, a.rounds),
        ],
    }
    await c.http.aclose()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    if any(s["violations"] or s["server_errors"] for s in report["scenarios"]):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
