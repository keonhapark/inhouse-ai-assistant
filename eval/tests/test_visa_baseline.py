import importlib.util
import json
import random
import sys

import pytest

from harness.paths import EVAL_DIR

pytest.importorskip("PIL")
pytest.importorskip("numpy")

spec = importlib.util.spec_from_file_location("visa_baseline", EVAL_DIR / "tools" / "visa_baseline.py")
vb = importlib.util.module_from_spec(spec)
sys.modules["visa_baseline"] = vb
spec.loader.exec_module(vb)


def make_dataset(root):
    """정상은 고른 회색 판, 불량은 흰 긁힘(scratch) 또는 검은 찍힘(dent)을 그린 판."""
    from PIL import Image, ImageDraw

    rng = random.Random(3)
    cls = root / "toy"
    cls.mkdir(parents=True)
    manifest, anno = [], ["object,split,label,image,mask"]
    for i in range(12):
        img = Image.new("RGB", (96, 96), (120 + rng.randint(-5, 5),) * 3)
        name = f"toy-normal-{i + 1:03d}.png"
        img.save(cls / name)
        src = f"VisA/toy/Data/Images/Normal/{i:03d}.JPG"
        manifest.append({"file": f"toy/{name}", "class": "toy", "kind": "normal", "source": src})
        anno.append(f"toy,train,normal,toy/Data/Images/Normal/{i:03d}.JPG,")
    for i in range(12):
        img = Image.new("RGB", (96, 96), (120,) * 3)
        g = ImageDraw.Draw(img)
        kind = "scratch" if i % 2 == 0 else "dent"
        if kind == "scratch":
            g.line([10, 10 + i, 86, 80 - i], fill=(255, 255, 255), width=4)
        else:
            g.ellipse([30, 30, 30 + 20 + i, 30 + 20 + i], fill=(10, 10, 10))
        name = f"toy-{i + 1:03d}.png"
        img.save(cls / name)
        src = f"VisA/toy/Data/Images/Anomaly/{i:03d}.JPG"
        manifest.append({"file": f"toy/{name}", "class": "toy", "kind": "anomaly", "source": src})
        anno.append(f"toy,test,{kind},toy/Data/Images/Anomaly/{i:03d}.JPG,mask.png")
    (root / "manifest.jsonl").write_text("".join(json.dumps(m) + "\n" for m in manifest), encoding="utf-8")
    (cls / "image_anno.csv").write_text("\n".join(anno) + "\n", encoding="utf-8")


def test_load_items_reads_defect_type_from_anno(tmp_path):
    make_dataset(tmp_path)
    items = vb.load_items(tmp_path)
    assert len(items) == 24
    assert {x["defect"] for x in items if x["kind"] == "anomaly"} == {"scratch", "dent"}
    assert all(x["defect"] is None for x in items if x["kind"] == "normal")


def test_baseline_separates_clear_defects(tmp_path):
    make_dataset(tmp_path)
    out = tmp_path / "res" / "toy"
    assert vb.main(["--data", str(tmp_path), "--out", str(out)]) == 0
    res = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert res["classes"]["toy"]["auroc"] > 0.9
    assert res["summary"]["typeAccuracy"]["N"] == 6 and res["summary"]["typeAccuracy"]["n"] >= 5
    assert "불량 유형 분류(1-NN)" in out.with_suffix(".md").read_text(encoding="utf-8")


def test_auroc():
    assert vb.auroc([0.1, 0.2], [0.3, 0.4]) == 1.0
    assert vb.auroc([0.3], [0.3]) == 0.5
    assert vb.auroc([], [1.0]) is None
