"""제조 팩 고정 데이터를 만듭니다.

Faker(ko_KR)와 시드를 고정해 같은 입력이면 같은 파일이 나옵니다. CI가 다시 만들어 비교합니다.
실행: uv run --project contracts python packs/manufacturing/fixtures/generate.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import yaml
from faker import Faker

SEED = 20261120
HERE = Path(__file__).resolve().parent
PACK = HERE.parent

# 팀별 인원(팀장 포함). 본부장 4명과 대표이사 1명을 더해 60명입니다.
TEAM_SIZES = {
    "hr": 5,
    "finance": 6,
    "general-affairs": 4,
    "sales": 9,
    "production-control": 8,
    "quality": 6,
    "procurement": 5,
    "rnd": 8,
    "it-ops": 4,
}
DIVISION_HEADS = ["mgmt", "sales-div", "production-div", "rnd-center"]

ROOMS = [
    {"id": "room-a", "name": "회의실 A", "floor": 3, "capacity": 4},
    {"id": "room-b", "name": "회의실 B", "floor": 3, "capacity": 6},
    {"id": "room-c", "name": "회의실 C", "floor": 4, "capacity": 8},
    {"id": "room-d", "name": "대회의실", "floor": 5, "capacity": 20},
    {"id": "room-e", "name": "연구소 회의실", "floor": 2, "capacity": 6},
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
    assert set(TEAM_SIZES) | set(DIVISION_HEADS) | {"ceo-office"} <= unit_ids

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
                    date_start=fake.date_object().replace(year=2008, month=1, day=1),
                    date_end=fake.date_object().replace(year=2026, month=6, day=30),
                ).isoformat(),
            }
        )

    add("ceo-office", "ceo")
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
