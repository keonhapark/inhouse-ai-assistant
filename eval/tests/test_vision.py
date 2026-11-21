"""이미지 첨부와 이미지 읽기 채점(#386)."""

import json

import pytest

from harness.attachments import AttachmentError, load_attachment
from harness.conversation import run_conversation
from harness.paths import EVAL_DIR
from harness.vision import load_truth, norm, run_items, score, score_defect, score_drawing, summarize

TRUTH = load_truth()


def test_truth_files_exist_and_attach():
    assert {t["kind"] for t in TRUTH} == {"drawing", "defect"}
    for t in TRUTH:
        a = load_attachment(t["file"])
        assert a["kind"] == "image" and a["dataUrl"].startswith("data:image/png;base64,")


def test_attachment_errors(tmp_path):
    (tmp_path / "x.gif").write_bytes(b"GIF89a")
    with pytest.raises(AttachmentError, match="jpeg·png"):
        load_attachment("x.gif", tmp_path)
    with pytest.raises(AttachmentError, match="없습니다"):
        load_attachment("none.png", tmp_path)


def test_norm_diameter_and_spaces():
    assert norm("Ø30 h7") == norm("DIA 30 h7") == norm("지름 30h7") == "DIA30H7"


def test_score_drawing():
    t = next(x for x in TRUTH if x["id"] == "dwg-001")
    answer = (f"부품 번호는 {t['part_no']}, 도면 이름 {t['title'].lower()}입니다. 치수: "
              + ", ".join(d.replace("DIA ", "Ø") for d in t["dimensions"]) + ". 주기: " + "; ".join(t["notes"]))
    s = score_drawing(answer, t)
    assert s.all_correct and s.found == s.total == 6
    s = score_drawing(f"부품 번호 {t['part_no']}만 보입니다.", t)
    assert s.fields == {"part_no": True, "title": False} and s.found == 0 and not s.all_correct


def test_score_defect_synonyms():
    t = next(x for x in TRUTH if x["id"] == "defect-001")
    assert score_defect("품목 BRG-6204, 외륜에 긁힘이 있습니다.", t).all_correct
    assert score_defect("ITEM brg 6204, scratch on outer ring", t).fields["defect_type"]
    assert not score_defect("품목 BRG-6205, 찍힘", t).all_correct


class EchoChat:
    """그림 정답을 그대로 읽어 주는 대상 시스템(첨부가 붙었는지도 봄)."""

    def __init__(self, truths):
        self.truths, self.seen = truths, []

    def start(self, requester):
        return "c1"

    def send(self, cid, text, attachments=None):
        self.seen.append((text, len(attachments or [])))
        t = self.truths[0]
        return [{"type": "message", "text": json.dumps(t, ensure_ascii=False)}, {"type": "done"}]


def test_run_items_and_summary():
    truths = [t for t in TRUTH if t["id"] in ("dwg-002", "defect-002")]
    chats = []

    def system():
        c = EchoChat([truths[len(chats)]])
        chats.append(c)
        return c

    rows = run_items(truths, system)
    assert [r["allCorrect"] for r in rows] == [True, True]
    assert all(c.seen[0][1] == 1 for c in chats)
    s = summarize(rows)
    assert s["drawing"]["allCorrect"] == 1 and s["defect"]["fields"] == {"defect_type": 1, "item_code": 1}


def test_conversation_sends_turn_attachments():
    class Chat:
        sent = []

        def start(self, requester):
            return "c1"

        def send(self, cid, text, attachments=None):
            Chat.sent.append(attachments)
            return [{"type": "message", "text": "읽었습니다."}, {"type": "done"}]

    s = {"id": "s", "requester": "E0050", "turns": [{"role": "user", "content": "도면 읽어 줘",
                                                       "attachments": ["images/drawings/dwg-001.png"]}],
         "expect": {"outcome": "completed"}}
    record = run_conversation(s, Chat())
    assert record.error is None and len(Chat.sent[0]) == 1


def test_generator_is_deterministic(tmp_path):
    pytest.importorskip("PIL")
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_images", EVAL_DIR / "tools/make_images.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main(["--out", str(tmp_path)])
    got = [json.loads(line) for line in (tmp_path / "truth.jsonl").read_text(encoding="utf-8").splitlines()]
    assert got == TRUTH


def _load_tool(name):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, EVAL_DIR / f"tools/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fetch_visa_takes_subset_and_renames(tmp_path):
    """묶음에서 범주마다 불량 사진 N장과 image_anno.csv만 꺼내고, 묶음 안 경로를 쓰지 않습니다."""
    import io
    import tarfile

    tar_path = tmp_path / "visa.tar"
    with tarfile.open(tar_path, "w") as tar:
        def add(name, data=b"x"):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        add("VisA/pcb1/image_anno.csv", b"object,split,label,image,mask\n")
        for k in range(4):
            add(f"VisA/pcb1/Data/Images/Anomaly/{k:03d}.JPG", bytes([k]))
            add(f"VisA/pcb1/Data/Images/Normal/{k:03d}.JPG")
        add("VisA/candle/Data/Images/Anomaly/000.JPG")
        add("VisA/pcb1/Data/Images/Anomaly/../../../../evil.JPG")
    mod = _load_tool("fetch_visa")
    out = tmp_path / "out"
    with open(tar_path, "rb") as f:
        rows = mod.extract(f, out, per_class=2, classes={"pcb1"})
    assert [r["file"] for r in rows] == ["pcb1/pcb1-001.jpg", "pcb1/pcb1-002.jpg"]
    assert (out / "pcb1/image_anno.csv").exists() and not (out / "candle").exists()
    assert not (tmp_path / "evil.JPG").exists()
    assert len((out / "manifest.jsonl").read_text().splitlines()) == 2


def test_fetch_visa_refuses_repo_output():
    mod = _load_tool("fetch_visa")
    with pytest.raises(SystemExit, match="저장소 밖"):
        mod.main(["--out", str(EVAL_DIR / "images/visa"), "--archive", "none.tar"])
