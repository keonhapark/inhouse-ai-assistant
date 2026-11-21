import importlib.util
import json
import sys

from harness.paths import EVAL_DIR
from harness.receipt_baseline import extract_fields
from harness.receipts import score

spec = importlib.util.spec_from_file_location("ocr_baseline", EVAL_DIR / "tools" / "ocr_baseline.py")
ob = importlib.util.module_from_spec(spec)
sys.modules["ocr_baseline"] = ob
spec.loader.exec_module(ob)


def test_regex_reads_every_dev_receipt_from_clean_text(tmp_path):
    """OCR이 완벽하면(생성기 줄 텍스트) 정규식이 개발 묶음 40장을 모두 맞혀야 합니다(정규식 상한)."""
    (tmp_path / "truth.jsonl").write_text((EVAL_DIR / "receipts/dev-truth.jsonl").read_text(encoding="utf-8"),
                                          encoding="utf-8")
    out = tmp_path / "out" / "oracle"
    assert ob.main(["--images", str(tmp_path), "--engine", "oracle", "--out", str(out)]) == 0
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["summary"]["allFields"]["n"] == data["summary"]["allFields"]["N"] == 40
    assert "네 필드 모두 | 40/40" in out.with_suffix(".md").read_text(encoding="utf-8")


def test_extract_from_noisy_lines():
    lines = ["영 수 증", "㈜솔빛유통", "사업자 번호: 2208162517", "일시 2027년 3월 9일 14:02",
             "생수 2L x2 2,400", "부가세 218", "합 계 ₩2,400"]
    got = extract_fields(lines)
    assert got == {"bizNo": "2208162517", "date": "2027년 3월 9일", "amount": 2400, "merchant": "㈜솔빛유통"}
    truth = {"id": "t", "amount": 2400, "date": "2027-03-09", "merchant": "(주)솔빛유통", "bizNo": "220-81-62517"}
    assert score(got, truth).all_correct


def test_amount_falls_back_to_largest_value_without_total_line():
    lines = ["가맹점 한빛문구", "사업자 484-82-16818", "거래일 26/05/08 15:25", "카드번호 5773-97**-****-6829",
             "김밥 x3 10,500", "볼펜 세트 x1 4,500"]
    got = extract_fields(lines)
    assert got["amount"] == 10500 and got["merchant"] == "한빛문구" and got["date"] == "26/05/08"


def test_ocr_mistakes_are_wrong():
    lines = ["한빛문구", "사업자번호 484-82-l68l8", "2O26.05.08", "합계 48,4OO"]
    got = extract_fields(lines)
    truth = {"id": "t", "amount": 48400, "date": "2026-05-08", "merchant": "한빛문구", "bizNo": "484-82-16818"}
    s = score(got, truth)
    assert s.merchant and not s.bizNo and not s.date and not s.amount
