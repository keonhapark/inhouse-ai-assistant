"""가짜 영수증 묶음을 만듭니다(#462, #100, 기획서 측정 설계 "이미지 읽기 평가").

가맹점·품목·금액·날짜·사업자번호를 생성기가 정하므로 정답 라벨이 정확합니다. 레이아웃(마트·음식점·카드 전표)과
날짜·금액 표기를 섞고, 기울기·흐림·구김·그림자를 줍니다. 생성 모델은 쓰지 않습니다.

- 정답 라벨은 시드만으로 정해지고 글꼴과 관계없습니다. 개발 묶음(시드 `DEV_SEED`)의 정답은 `receipts/dev-truth.jsonl`로
  커밋합니다. 확인 묶음은 다른 시드를 실행 때만 주고(`--set confirm --seed <값>`), 저장소 안에는 쓰지 않습니다.
- 한글을 그리려면 한글 글꼴이 필요합니다. `--font`로 라이선스가 분명한 글꼴(예: Noto Sans KR, SIL OFL)을 주고,
  쓴 글꼴 파일의 sha256을 `manifest.json`에 남깁니다. 그림은 저장소 밖에 만듭니다.

    uv run --group tools python tools/make_receipts.py --out <저장소 밖 폴더> --font <NotoSansKR-Regular.ttf> [--n 40]
    uv run --group tools python tools/make_receipts.py --set confirm --seed <비공개 값> --out <저장소 밖> --font ...
    uv run python tools/make_receipts.py --truth-only --out receipts/dev-truth.jsonl   # 개발 정답만(그림 없음)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parents[1]
REPO = EVAL_DIR.parent
DEV_SEED = 20261122
DEV_N = 40
LAYOUTS = ("mart", "restaurant", "card_slip")
DATE_FORMATS = ("iso", "dot", "slash_short", "korean")
AMOUNT_FORMATS = ("comma", "comma_won", "won_sign", "plain")

MERCHANTS = ["바른마트 역삼점", "해오름김밥", "한빛문구", "새솔약국", "다온카페 본점", "온누리편의점 서초점", "가람식당",
             "푸른주유소", "모아철물", "은하분식", "(주)나래상사", "㈜솔빛유통", "늘봄베이커리", "청솔한식뷔페", "들꽃꽃집",
             "다래서점", "빛고을정육점", "한결세탁", "새벽택배 영업소", "하늘빛안경"]
ITEMS = [("생수 2L", 1200), ("A4 용지", 5900), ("볼펜 세트", 4500), ("김밥", 3500), ("라면", 4000), ("아메리카노", 4100),
         ("카페라테", 4800), ("샌드위치", 5500), ("복사 용역", 3000), ("택배비", 4000), ("휘발유", 1689), ("우유 1L", 2900),
         ("커피믹스", 12800), ("물티슈", 2000), ("건전지 AA", 6500), ("점심 정식", 9000), ("제육볶음", 10000),
         ("세탁비", 7000), ("안경닦이", 3000), ("케이크", 25000)]


def biz_no(rng: random.Random) -> str:
    """검증 숫자가 맞는 사업자등록번호(가상)."""
    d = [rng.randint(0, 9) for _ in range(9)]
    d[0] = rng.randint(1, 9)
    w = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    s = sum(a * b for a, b in zip(d, w)) + (d[8] * 5) // 10
    d.append((10 - s % 10) % 10)
    x = "".join(map(str, d))
    return f"{x[:3]}-{x[3:5]}-{x[5:]}"


def biz_no_valid(text: str) -> bool:
    x = "".join(c for c in text if c.isdigit())
    if len(x) != 10:
        return False
    d = list(map(int, x))
    w = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    s = sum(a * b for a, b in zip(d[:9], w)) + (d[8] * 5) // 10
    return (10 - s % 10) % 10 == d[9]


def fmt_date(d: date, style: str) -> str:
    return {"iso": d.isoformat(), "dot": d.strftime("%Y.%m.%d"), "slash_short": d.strftime("%y/%m/%d"),
            "korean": f"{d.year}년 {d.month}월 {d.day}일"}[style]


def fmt_amount(n: int, style: str) -> str:
    return {"comma": f"{n:,}", "comma_won": f"{n:,}원", "won_sign": f"₩{n:,}", "plain": str(n)}[style]


def make_label(rng: random.Random, set_name: str, i: int) -> dict[str, Any]:
    lines = []
    for name, price in rng.sample(ITEMS, rng.randint(1, 5)):
        qty = rng.randint(1, 4)
        lines.append({"name": name, "qty": qty, "unit": price, "amount": qty * price})
    total = sum(x["amount"] for x in lines)
    day = date(2026, 1, 1) + timedelta(days=rng.randint(0, 455))
    distortion = {"angle": round(rng.uniform(-7, 7), 1), "blur": rng.choice([0, 0, 0.6, 1.2]),
                  "crumple": rng.choice([0, 0, 1, 2]), "shadow": rng.choice([False, False, True])}
    return {
        "id": f"rcp-{set_name}-{i + 1:03d}",
        "set": set_name,
        "merchant": rng.choice(MERCHANTS),
        "bizNo": biz_no(rng),
        "date": day.isoformat(),
        "time": f"{rng.randint(8, 21):02d}:{rng.randint(0, 59):02d}",
        "amount": total,
        "vat": round(total / 11),
        "items": lines,
        "card": f"{rng.randint(4000, 5999)}-{rng.randint(10, 99)}**-****-{rng.randint(1000, 9999)}",
        "layout": rng.choice(LAYOUTS),
        "dateFormat": rng.choice(DATE_FORMATS),
        "amountFormat": rng.choice(AMOUNT_FORMATS),
        "distortion": distortion,
    }


def make_labels(seed: int, set_name: str, n: int) -> list[dict[str, Any]]:
    rng = random.Random(f"{set_name}:{seed}")
    return [make_label(rng, set_name, i) for i in range(n)]


def receipt_lines(label: dict[str, Any]) -> list[tuple[str, str]]:
    """(정렬, 글) 줄 목록. 정렬은 center·left·pair(왼쪽|오른쪽)."""
    amt = lambda n: fmt_amount(n, label["amountFormat"])  # noqa: E731
    d = fmt_date(date.fromisoformat(label["date"]), label["dateFormat"])
    head = [("center", label["merchant"]), ("center", f"사업자번호 {label['bizNo']}")]
    items = [("pair", f"{x['name']} x{x['qty']}|{amt(x['amount'])}") for x in label["items"]]
    tail = [("pair", f"부가세|{amt(label['vat'])}"), ("pair", f"합계|{amt(label['amount'])}")]
    if label["layout"] == "mart":
        return head + [("left", f"{d} {label['time']}"), ("left", "-" * 30)] + items + [("left", "-" * 30)] + tail + \
            [("left", f"카드 {label['card']}")]
    if label["layout"] == "restaurant":
        return [("center", "영 수 증")] + head + [("left", f"일시 {d} {label['time']}")] + items + tail + \
            [("center", "감사합니다")]
    return [("center", "신용카드 매출전표"), ("left", f"가맹점 {label['merchant']}"), ("left", f"사업자 {label['bizNo']}"),
            ("left", f"거래일 {d} {label['time']}"), ("left", f"카드번호 {label['card']}"),
            ("pair", f"승인금액|{amt(label['amount'])}"), ("pair", f"부가세|{amt(label['vat'])}")]


def render(label: dict[str, Any], font_path: str | None, seed_tag: str) -> Any:
    """영수증 그림. font_path가 없으면 Pillow 내장 글꼴(한글이 그려지지 않음, 시험용)."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    rng = random.Random(f"render:{seed_tag}:{label['id']}")
    size = 26
    f = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default(size=size)
    lines = receipt_lines(label)
    w, h = 560, 80 + len(lines) * (size + 14)
    img = Image.new("RGB", (w, h), (250, 249, 244))
    g = ImageDraw.Draw(img)
    y = 40
    for align, text in lines:
        if align == "pair":
            left, right = text.split("|")
            g.text((30, y), left, fill="black", font=f)
            g.text((w - 30 - g.textlength(right, font=f), y), right, fill="black", font=f)
        elif align == "center":
            g.text(((w - g.textlength(text, font=f)) / 2, y), text, fill="black", font=f)
        else:
            g.text((30, y), text, fill="black", font=f)
        y += size + 14
    dist = label["distortion"]
    if dist["crumple"]:  # 가로 줄마다 조금씩 밀어 구김을 흉내냅니다
        amp, period = 2 + 2 * dist["crumple"], rng.uniform(40, 90)
        out = Image.new("RGB", img.size, (250, 249, 244))
        for yy in range(h):
            dx = int(amp * math.sin(yy / period * 2 * math.pi + rng.random() * 0.2))
            out.paste(img.crop((0, yy, w, yy + 1)), (dx, yy))
        img = out
    if dist["shadow"]:
        shade = Image.linear_gradient("L").resize(img.size).point(lambda v: 255 - v // 4)
        img = Image.composite(img, Image.new("RGB", img.size, (150, 150, 150)), shade)
    if dist["blur"]:
        img = img.filter(ImageFilter.GaussianBlur(dist["blur"]))
    if dist["angle"]:
        img = img.rotate(dist["angle"], expand=True, fillcolor=(205, 205, 200), resample=Image.BICUBIC)
    return img


def write_truth(labels: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in labels), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", choices=["dev", "confirm"], default="dev")
    ap.add_argument("--seed", type=int, help="확인 묶음은 반드시 줌(저장소에 남기지 않음). 개발은 DEV_SEED")
    ap.add_argument("--n", type=int, default=DEV_N)
    ap.add_argument("--out", required=True, type=Path, help="그림 폴더, --truth-only면 정답 파일 경로")
    ap.add_argument("--font", help="한글 글꼴 파일(라이선스가 분명한 것)")
    ap.add_argument("--truth-only", action="store_true", help="그림 없이 정답 라벨만 씀")
    args = ap.parse_args(argv)
    if args.set == "confirm":
        if args.seed is None:
            raise SystemExit("확인 묶음은 --seed를 줍니다(개발 시드와 달라야 하고 저장소에 남기지 않음)")
        if args.seed == DEV_SEED:
            raise SystemExit("확인 묶음 시드는 개발 시드와 달라야 합니다")
        if REPO in args.out.resolve().parents or args.out.resolve() == REPO:
            raise SystemExit("확인 묶음은 저장소 밖에 씁니다")
    seed = args.seed if args.seed is not None else DEV_SEED
    labels = make_labels(seed, args.set, args.n)
    if args.truth_only:
        write_truth(labels, args.out)
        print(f"정답 {len(labels)}개: {args.out}")
        return 0
    if not args.font:
        raise SystemExit("그림을 만들려면 한글 글꼴(--font)을 줍니다")
    args.out.mkdir(parents=True, exist_ok=True)
    for x in labels:
        render(x, args.font, f"{args.set}:{seed}").save(args.out / f"{x['id']}.png")
    write_truth(labels, args.out / "truth.jsonl")
    font = Path(args.font)
    (args.out / "manifest.json").write_text(json.dumps({
        "set": args.set, "n": len(labels), "font": font.name, "fontSha256": hashlib.sha256(font.read_bytes()).hexdigest(),
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.out.glob("*.png"))},
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"영수증 {len(labels)}장: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
