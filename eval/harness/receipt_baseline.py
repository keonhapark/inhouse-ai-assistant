"""영수증 전통 기준선: OCR 텍스트에서 정규식으로 네 필드를 뽑습니다(#463, #100).

OCR 엔진은 바꿔 끼웁니다(`tools/ocr_baseline.py`). 이 모듈은 엔진이 낸 줄 텍스트만 받고, 뽑은 값은
`harness/receipts.py` 채점기로 셉니다. 규칙은 영수증 생성기의 정답을 보지 않고 영수증 표기 관행으로 정했습니다.

- 사업자번호: `000-00-00000` 꼴, 없으면 "사업자" 뒤 숫자 10자리
- 날짜: `YYYY-MM-DD`·`YYYY.MM.DD`·`YYYY/MM/DD`·`YY/MM/DD`·`YYYY년 M월 D일` 중 처음 나온 것
- 금액: 영수증에서 합계는 품목·부가세보다 크므로, 사업자번호·카드번호·날짜·시각을 뺀 금액 중 가장 큰 값.
  OCR이 기운 영수증에서 라벨과 금액을 다른 줄로 묶어도 버팁니다(#463 개발 묶음에서 "합계 줄의 마지막 금액" 규칙이
  회전 때문에 부가세를 고르던 것을 보고 바꿈)
- 가맹점: "가맹점" 뒤 글, 없으면 머리글(영수증·매출전표 등)·날짜 라벨(일시·거래일·날짜) 줄과 숫자로 시작하는 줄을 뺀 첫 줄
"""

from __future__ import annotations

import re
from typing import Any

BIZ = re.compile(r"(\d{3})\s*-\s*(\d{2})\s*-\s*(\d{5})")
BIZ_LABELED = re.compile(r"사업자\D{0,8}((?:\d[\s-]?){10})")
DATE = re.compile(r"(\d{4}\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{1,2}|\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"
                  r"|(?<!\d)\d{2}/\d{1,2}/\d{1,2}(?!\d))")
MONEY = re.compile(r"(?:₩|￦)?\s*(\d{1,3}(?:,\d{3})+|\d+)\s*원?")
HEADERS = ("영수증", "영 수 증", "매출전표", "신용카드", "RECEIPT", "일시", "거래일", "날짜", "카드번호")


def _money_values(line: str) -> list[int]:
    out = []
    for m in MONEY.finditer(line):
        digits = m.group(1).replace(",", "")
        if digits.isdigit():
            out.append(int(digits))
    return out


def extract_fields(lines: list[str]) -> dict[str, Any]:
    text = "\n".join(lines)
    fields: dict[str, Any] = {}
    m = BIZ.search(text)
    if m:
        fields["bizNo"] = "-".join(m.groups())
    else:
        m = BIZ_LABELED.search(text)
        if m:
            fields["bizNo"] = re.sub(r"\D", "", m.group(1))
    m = DATE.search(text)
    if m:
        fields["date"] = m.group(1)
    # 사업자번호·카드번호·날짜·시각 속 숫자는 금액 후보에서 뺍니다
    cleaned = BIZ.sub(" ", DATE.sub(" ", text))
    cleaned = re.sub(r"\d{4}-\d{2}[*_]{2}[-_]\*{4}[-_]?\d{4}|\d{1,2}:\d{2}|사업자\D{0,8}(?:\d[\s-]?){10}", " ", cleaned)
    values = _money_values(cleaned)
    if values:
        fields["amount"] = max(values)
    merchant = None
    for ln in lines:
        m = re.search(r"가맹점(?:명)?\s*[:：]?\s*(.+)", ln)
        if m:
            merchant = m.group(1).strip()
            break
    if merchant is None:
        for ln in lines:
            s = ln.strip()
            if not s or any(h.replace(" ", "") in s.replace(" ", "") for h in HEADERS) or s[0].isdigit() \
                    or s.startswith(("사업자", "-", "=")):
                continue
            merchant = s
            break
    if merchant:
        fields["merchant"] = merchant
    return fields
