"""가짜 영수증 읽기 채점(#462, #100): 금액·날짜·가맹점·사업자번호 필드 완전 일치.

읽은 값(예측)은 필드 네 개를 가진 객체입니다. 모델 답에서 JSON을 꺼낼 때는 `prediction_from_text`를 씁니다.
비교 전에 표기 차이만 정규화합니다. 정규화 규칙은 아래 함수마다 적었고, 그 밖의 차이는 틀림입니다.

- 금액: 통화 기호(₩, 원, KRW)·쉼표·공백·천 단위 마침표를 지운 정수. "1만 2,500원"처럼 만·천 단위도 읽습니다.
- 날짜: `YYYY-MM-DD`, `YYYY.MM.DD`, `YYYY/MM/DD`, `YY/MM/DD`(2000년대), `YYYY년 M월 D일` → ISO 날짜
- 사업자번호: 숫자만 남긴 10자리
- 가맹점: 유니코드 NFKC, 공백 제거, 법인 표기(`(주)`·`㈜`·`주식회사`)를 하나로
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any


FIELDS = ("amount", "date", "merchant", "bizNo")
_UNITS = {"억": 100_000_000, "만": 10_000, "천": 1_000, "백": 100}


def norm_amount(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"(₩|￦|원|KRW|krw|\s|,)", "", text)
    if not text:
        return None
    if any(u in text for u in _UNITS):
        total, rest = 0, text
        for unit, mult in _UNITS.items():
            if unit in rest:
                head, rest = rest.split(unit, 1)
                if head and not head.isdigit():
                    return None
                total += (int(head) if head else 1) * mult
        if rest:
            if not rest.isdigit():
                return None
            total += int(rest)
        return total
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", text):  # 1.234.500 같은 천 단위 마침표
        text = text.replace(".", "")
    return int(text) if text.isdigit() else None


def norm_date(value: Any) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    m = re.fullmatch(r"(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})\.?", text) or \
        re.fullmatch(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", text)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})", text)
        if not m:
            return None
        y, mo, d = 2000 + int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def norm_biz_no(value: Any) -> str | None:
    if value is None:
        return None
    digits = "".join(c for c in unicodedata.normalize("NFKC", str(value)) if c.isdigit())
    return digits if len(digits) == 10 else None


def norm_merchant(value: Any) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value))  # ㈜ → (주)
    text = re.sub(r"\s+", "", text).replace("주식회사", "(주)")
    return text or None


NORMALIZERS = {"amount": norm_amount, "date": norm_date, "merchant": norm_merchant, "bizNo": norm_biz_no}


@dataclass
class ReceiptScore:
    id: str
    amount: bool
    date: bool
    merchant: bool
    bizNo: bool

    @property
    def all_correct(self) -> bool:
        return self.amount and self.date and self.merchant and self.bizNo


def score(prediction: dict[str, Any] | None, truth: dict[str, Any]) -> ReceiptScore:
    p = prediction or {}
    ok = {}
    for f in FIELDS:
        got = NORMALIZERS[f](p.get(f))
        ok[f] = got is not None and got == NORMALIZERS[f](truth[f])
    return ReceiptScore(id=truth["id"], **ok)


def prediction_from_text(text: str) -> dict[str, Any] | None:
    """모델 답에서 마지막 JSON 객체를 꺼냅니다(코드 블록 안이어도 됨). 없으면 None(네 필드 모두 틀림)."""
    candidates = re.findall(r"\{[^{}]*\}", text or "")
    for c in reversed(candidates):
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and any(k in obj for k in FIELDS):
            return obj
    return None


def load_truth(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def summarize(scores: list[ReceiptScore], truths: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """필드별·전체 완전 일치(Clopper-Pearson 95%)와, 정답을 주면 레이아웃·왜곡별 전체 완전 일치."""
    from harness.report import proportion as rate  # 보고서와 같은 형식(n, N, rate, low, high)

    n = len(scores)
    out = {"items": n, "allFields": rate(sum(s.all_correct for s in scores), n),
           "fields": {f: rate(sum(getattr(s, f) for s in scores), n) for f in FIELDS}}
    if truths:
        by_id = {t["id"]: t for t in truths}
        groups: dict[str, list[ReceiptScore]] = {}
        for s in scores:
            t = by_id[s.id]
            dist = t.get("distortion", {})
            heavy = abs(dist.get("angle", 0)) >= 4 or dist.get("blur", 0) >= 1 or dist.get("crumple", 0) >= 2
            for key in (f"layout:{t.get('layout')}", f"distortion:{'heavy' if heavy else 'light'}"):
                groups.setdefault(key, []).append(s)
        out["groups"] = {k: rate(sum(s.all_correct for s in v), len(v)) for k, v in sorted(groups.items())}
    return out


def score_rows(predictions: dict[str, dict[str, Any] | None], truths: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """id → 예측 사전에서 회차 기록 행을 만듭니다. 예측이 없는 항목은 네 필드 모두 틀림입니다."""
    rows = []
    for t in truths:
        s = score(predictions.get(t["id"]), t)
        rows.append({**asdict(s), "allCorrect": s.all_correct})
    return rows
