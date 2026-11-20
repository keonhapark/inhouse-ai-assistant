"""실제 erp에 돌릴 행동 계약 시험 목록을 출력합니다(CI erp job).

erp/ci/behavior-tests.txt가 있으면 거기 적힌 시험 이름(한 줄에 하나, # 주석)만,
없으면 tests/test_erp_behavior.py 전체입니다. erp가 기능을 나눠 만드는 동안 구현한 만큼만
돌리고(비어 있으면 건너뜀), 1단계 마지막 erp 이슈에서 이 파일을 지워 전체(40개)를 돌립니다.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIST = ROOT / "erp/ci/behavior-tests.txt"
TARGET = "tests/test_erp_behavior.py"

if LIST.exists():
    names = [x.split("#")[0].strip() for x in LIST.read_text(encoding="utf-8").splitlines()]
    names = [n for n in names if n]
    print(" ".join(f"{TARGET}::{n}" for n in names))
else:
    print(TARGET)
