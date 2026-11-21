import importlib.util
import json

import pytest

from harness.paths import EVAL_DIR

spec = importlib.util.spec_from_file_location("mask_toolcall", EVAL_DIR / "tools" / "mask_toolcall.py")
mt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mt)

ROW = {"repeat": 1, "agentId": "hr", "variant": {}, "model": "local", "status": 200, "wallMs": 10,
       "result": {"tool": "leave_request", "arguments": {"reason": "시험용 사유 큐피-17"}}, "id": "tc-001",
       "target_tool": "leave_request", "category": "direct", "stage": 1, "expected_type": "call",
       "outcome": "wrong_args", "passed": False, "tool": "leave_request", "asked": False,
       "mismatched": ["reason"], "schema_valid": True, "schema_errors": [], "fabricated": 0, "latency_ms": 9,
       "location": "local", "error": None}


def write(tmp_path, rows):
    items = tmp_path / "items.jsonl"
    items.write_text(json.dumps({"id": "tc-001", "utterance": "시험용 발화 큐피-17 처리해 줘",
                                 "expected": {"type": "call", "tool": "leave_request",
                                              "args": {"reason": "시험용 사유 큐피-17", "kind_x": "ave_req"}}},
                                ensure_ascii=False) + "\n", encoding="utf-8")
    run = tmp_path / "orig" / "r"
    run.parent.mkdir()
    meta = {"title": "t", "repeats": 1, "notes": []}
    run.with_suffix(".json").write_text(json.dumps({"meta": meta, "summary": {}, "rows": rows}, ensure_ascii=False),
                                        encoding="utf-8")
    run.with_suffix(".rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                              encoding="utf-8")
    return items, run


def test_drops_item_fields_and_wrong_args_section(tmp_path):
    items, run = write(tmp_path, [ROW, ROW | {"id": "tc-002", "error": "HTTP 502 body", "status": 502}])
    out = tmp_path / "pub" / "r"
    mt.main(["--items", str(items), "--run", str(run), "--out", str(out), "--note", "메모"])
    text = "".join(out.with_suffix(s).read_text(encoding="utf-8") for s in (".json", ".rows.jsonl", ".md"))
    assert "큐피-17" not in text and "## 인자 틀림" not in text
    rows = [json.loads(x) for x in out.with_suffix(".rows.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(not set(mt.DROP) & set(r) for r in rows) and rows[1]["error"] == "실행 오류(HTTP 502)"
    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["meta"]
    assert meta["notes"][0] == "메모" and "r.rows.jsonl sha256" in meta["notes"][1]
    # kind_x 값 "ave_req"는 공개 식별자 leave_request의 일부라 남은 것으로 세지 않습니다
    assert "leave_request" in text


def test_refuses_when_item_text_would_remain(tmp_path):
    items, run = write(tmp_path, [ROW])
    with pytest.raises(SystemExit, match="문항 문자열"):
        mt.main(["--items", str(items), "--run", str(run), "--out", str(tmp_path / "pub" / "r"),
                 "--note", "예: 시험용 사유 큐피-17"])
    assert not (tmp_path / "pub").exists()
