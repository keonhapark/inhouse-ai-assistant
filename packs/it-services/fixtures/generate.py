"""IT 서비스 팩 고정 데이터를 만듭니다(제조·금융 팩 생성기와 같은 방식).

Faker(ko_KR)와 시드를 고정해 같은 입력이면 같은 파일이 나옵니다.
실행: uv run --project contracts python packs/it-services/fixtures/generate.py
고객사(customers.json)와 티켓(tickets.json)은 손으로 쓴 파일이라 이 생성기가 건드리지 않습니다.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import yaml
from faker import Faker

SEED = 20261122
HERE = Path(__file__).resolve().parent
PACK = HERE.parent

# 팀별 인원(팀장 포함). 사업부장 3명과 대표이사 1명을 더해 36명입니다.
TEAM_SIZES = {
    "si-public": 7,
    "si-enterprise": 7,
    "ito-ops": 5,
    "ito-desk": 5,
    "pmo": 4,
    "people-ops": 4,
}
DIVISION_HEADS = ["si-div", "ito-div", "biz-div"]
CEO_UNIT = "sol-ceo"

ROOMS = [
    {"id": "room-a", "name": "회의실 1", "floor": 7, "capacity": 6},
    {"id": "room-b", "name": "회의실 2", "floor": 7, "capacity": 8},
    {"id": "room-c", "name": "프로젝트 룸", "floor": 8, "capacity": 12},
    {"id": "room-d", "name": "대회의실", "floor": 9, "capacity": 20},
]


def unique_name(fake: Faker, used: set[str]) -> str:
    while True:
        name = fake.name()
        if name not in used:
            used.add(name)
            return name


def build() -> dict[str, object]:
    fake = Faker("ko_KR")
    Faker.seed(SEED)
    rng = random.Random(SEED)
    org = yaml.safe_load((PACK / "org.yaml").read_text(encoding="utf-8"))
    unit_ids = {u["id"] for u in org["units"]}
    assert set(TEAM_SIZES) | set(DIVISION_HEADS) | {CEO_UNIT} <= unit_ids

    used: set[str] = set()
    employees: list[dict[str, object]] = []

    def add(unit: str, grade: str) -> None:
        no = f"E{len(employees) + 1:04d}"
        employees.append(
            {
                "id": no,
                "employee_no": no,
                "name": unique_name(fake, used),
                "unit_id": unit,
                "grade": grade,
                "email": f"{no.lower()}@example.invalid",
                "hired_on": fake.date_between_dates(
                    date_start=fake.date_object().replace(year=2010, month=1, day=1),
                    date_end=fake.date_object().replace(year=2026, month=6, day=30),
                ).isoformat(),
            }
        )

    add(CEO_UNIT, "ceo")
    for div in DIVISION_HEADS:
        add(div, "division_head")
    for team, size in TEAM_SIZES.items():
        add(team, "team_leader")
        for _ in range(size - 1):
            add(team, "staff")

    balances = []
    for e in employees:
        total = rng.choice([15, 15, 16, 17, 18, 20])
        used_days = rng.randint(0, 8) + rng.choice([0, 0.5])
        balances.append(
            {
                "employee_id": e["id"],
                "year": 2026,
                "annual_total": float(total),
                "annual_used": float(used_days),
            }
        )

    return {
        "employees.json": {"seed": SEED, "employees": employees},
        "rooms.json": {"rooms": ROOMS},
        "leave_balances.json": {"seed": SEED, "balances": balances},
    }


def main() -> None:
    for name, data in build().items():
        (HERE / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
