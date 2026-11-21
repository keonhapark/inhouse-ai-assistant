import importlib.util
import json
import sys

import pytest

from harness.paths import EVAL_DIR
from harness.receipts import (FIELDS, load_truth, norm_amount, norm_biz_no, norm_date, norm_merchant,
                              prediction_from_text, score, score_rows, summarize)

spec = importlib.util.spec_from_file_location("make_receipts", EVAL_DIR / "tools" / "make_receipts.py")
mr = importlib.util.module_from_spec(spec)
sys.modules["make_receipts"] = mr
spec.loader.exec_module(mr)
DEV = EVAL_DIR / "receipts" / "dev-truth.jsonl"


def test_dev_truth_is_reproducible_from_seed():
    assert load_truth(DEV) == mr.make_labels(mr.DEV_SEED, "dev", mr.DEV_N)


def test_labels_are_consistent():
    labels = mr.make_labels(mr.DEV_SEED, "dev", mr.DEV_N)
    assert all(mr.biz_no_valid(x["bizNo"]) for x in labels)
    assert all(x["amount"] == sum(i["amount"] for i in x["items"]) for x in labels)
    assert {x["layout"] for x in labels} == set(mr.LAYOUTS)
    assert not mr.biz_no_valid("123-45-67891") or not mr.biz_no_valid("123-45-67892")


def test_confirm_set_uses_other_seed_outside_repo(tmp_path):
    confirm = mr.make_labels(12345, "confirm", 10)
    dev = mr.make_labels(mr.DEV_SEED, "dev", 10)
    assert {x["bizNo"] for x in confirm}.isdisjoint({x["bizNo"] for x in dev})
    with pytest.raises(SystemExit, match="--seed"):
        mr.main(["--set", "confirm", "--out", str(tmp_path), "--truth-only"])
    with pytest.raises(SystemExit, match="개발 시드와 달라야"):
        mr.main(["--set", "confirm", "--seed", str(mr.DEV_SEED), "--out", str(tmp_path), "--truth-only"])
    with pytest.raises(SystemExit, match="저장소 밖"):
        mr.main(["--set", "confirm", "--seed", "7", "--out", str(EVAL_DIR / "receipts" / "x.jsonl"), "--truth-only"])
    assert mr.main(["--set", "confirm", "--seed", "7", "--out", str(tmp_path / "t.jsonl"), "--truth-only"]) == 0


def test_render_smoke(tmp_path):
    pytest.importorskip("PIL")
    label = mr.make_labels(mr.DEV_SEED, "dev", 3)[2]
    label["distortion"] = {"angle": 3.0, "blur": 0.6, "crumple": 2, "shadow": True}
    img = mr.render(label, None, "test")  # 내장 글꼴(한글은 그려지지 않음)
    assert img.size[0] > 560 and img.size[1] > 100


@pytest.mark.parametrize("value, want", [("₩12,800", 12800), ("12,800원", 12800), ("1만 2,800원", 12800),
                                         ("1만2천5백원", 12500), ("1.234.500", 1234500), ("KRW 5,000", 5000),
                                         (12800, 12800), (12800.0, 12800), ("12.8", None), ("일만", None),
                                         (None, None), (True, None)])
def test_norm_amount(value, want):
    assert norm_amount(value) == want


@pytest.mark.parametrize("value, want", [("2027-03-09", "2027-03-09"), ("2027.3.9", "2027-03-09"),
                                         ("27/03/09", "2027-03-09"), ("2027년 3월 9일", "2027-03-09"),
                                         ("2027-02-30", None), ("03/09/2027", None)])
def test_norm_date(value, want):
    assert norm_date(value) == want


def test_norm_biz_no_and_merchant():
    assert norm_biz_no("123-45-67890") == "1234567890" and norm_biz_no("123-45-6789") is None
    assert norm_merchant("㈜ 솔빛 유통") == norm_merchant("주식회사솔빛유통") == norm_merchant("(주)솔빛유통")
    assert norm_merchant("솔빛유통 본점") != norm_merchant("솔빛유통")


def test_score_and_summary():
    truth = {"id": "r1", "amount": 48400, "date": "2026-05-08", "merchant": "한빛문구", "bizNo": "484-82-16818",
             "layout": "mart", "distortion": {"angle": 5.5, "blur": 1.2, "crumple": 2}}
    good = {"amount": "₩48,400", "date": "26/05/08", "merchant": "한빛 문구", "bizNo": "4848216818"}
    s = score(good, truth)
    assert s.all_correct
    bad = score({**good, "amount": "48,000"}, truth)
    assert not bad.all_correct and not bad.amount and bad.date
    assert not score(None, truth).all_correct
    out = summarize([s, bad], [truth, {**truth, "id": "r1"}])
    assert out["allFields"]["n"] == 1 and out["fields"]["amount"]["n"] == 1 and set(out["fields"]) == set(FIELDS)
    assert out["groups"]["distortion:heavy"]["of"] == 2
    rows = score_rows({"r1": good}, [truth, {**truth, "id": "r2"}])
    assert [r["allCorrect"] for r in rows] == [True, False]


def test_prediction_from_text():
    text = "읽은 값입니다.\n```json\n{\"amount\": \"12,800\", \"date\": \"2027-03-09\"}\n```"
    assert prediction_from_text(text) == {"amount": "12,800", "date": "2027-03-09"}
    assert prediction_from_text("모르겠습니다") is None
    assert prediction_from_text(json.dumps({"x": 1})) is None
