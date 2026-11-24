# 도면 난이도 단계와 OCR+BM25 기준선(#504)

#503의 도면 OCR+BM25 기준선(rag `bench/drawing_ocr.py`)이 1단계 도면에서 부품 번호 60/60·여섯 항목 360/360으로 천장이라 비전 모델과 견줄 수 없었습니다. 도면 생성기(`tools/make_images.py`)에 실제 도면에 가까운 변형을 단계로 더하고, 같은 기준선을 단계마다 다시 쟀습니다.

## 단계

| 단계 | 변형 |
|---|---|
| 1 | 지금까지의 깨끗한 그림(흰 배경, 큰 글씨). 같은 시드면 같은 그림이라 커밋한 `images/`와 #503 결과가 그대로입니다 |
| 2 | 작은 글씨(0.62배), 세워 쓴 길이 치수, 지름 치수 글자를 가로지르는 지시선, 한 자리만 다른 비슷한 부품 번호(개정 이력 "REPLACES") |
| 3 | 2에 표제란 표(칸 나눔, 도면 번호·시트·작성자 칸)와 스캔 흉내(회색 종이, 점 잡음, 흐림, ±3° 기울기) |

정답 항목(부품 번호·도면 이름·치수 네 개·주기 두 개)은 단계와 관계없이 같고, 채점기(`harness/vision.py` `score_drawing`)도 같습니다. 2·3단계와 확인 묶음 그림은 저장소 밖에 만듭니다(`--level`, `--set confirm --seed <개발 시드가 아닌 값>`).

## 결과(시드 7, 단계마다 60장, CPU)

| 단계 | 엔진 | 부품 번호 상위1 | 치수 상위1 / 상위5 | 끝까지 모두 맞음(장) | 여섯 항목 | OCR p50 |
|---|---|---|---|---|---|---|
| 1 | rapidocr | 60 | 52 / 60 | 60 | 360/360 | 0.98초 |
| 2 | rapidocr | 60 | 46 / 57 | 12 | 284/360 | 0.87초 |
| 3 | rapidocr | 60 | 4 / 44 | 2 | 244/360 | 1.04초 |
| 1·2·3 | oracle(정답 글자) | 60 | 58·60·60 / 60 | 60 | 360/360 | - |

- **2·3단계에서는 기준선이 천장에서 내려옵니다.** 1단계 60/60이던 "끝까지 모두 맞음"이 2단계 12/60, 3단계 2/60입니다. 비전 모델과 견줄 여지가 생겼습니다.
- 부품 번호 찾기는 비슷한 번호가 있어도 60/60입니다. 질의에 부품 번호가 그대로 들어가 BM25가 그 도면을 고르기 때문입니다. 비슷한 번호의 효과는 부품 번호를 "읽는" 과제(비전 모델 답의 채점)에서 드러납니다.
- 3단계의 치수 상위1이 4/60으로 떨어졌습니다. oracle(정답 글자)은 60/60이라 검색이 아니라 OCR 쪽에서 치수 글자를 잃은 것으로 보이지만, 장별 원인은 보지 않았습니다.
- 1단계 rapidocr 결과는 #503의 기록(치수 상위1 52/60, 360/360)과 같습니다.

## 조건과 다시 재는 방법

- 측정 커밋: `73fb518`(#511 병합 커밋). 측정은 병합 전 브랜치에서 했고, 생성기(`eval/tools/make_images.py`)와 OCR 기준선(`rag/bench/drawing_ocr.py`)은 이 커밋과 같습니다. 다시 잴 때는 이 커밋을 체크아웃합니다(protocol 8절).
- OCR: rag `ocr` 의존 그룹의 rapidocr-onnxruntime 1.4.4(Apache-2.0), WSL2 CPU. rag 코드는 고치지 않고, 생성기 단계만 바꿔 불렀습니다(아래 스크립트 요지).
- 결과 기록: `2026-11-22-drawing-levels.json`(엔진·단계별 요약)

```
cd rag && uv run --group ocr python - <<'PY'
import functools, sys; sys.path[:0] = [".", "bench", "../eval/tools"]
import drawing_ocr, make_images, tempfile; from pathlib import Path
make_images.drawing = functools.partial(make_images.drawing, level=3)
with tempfile.TemporaryDirectory() as d:
    t = drawing_ocr.make_drawings(60, Path(d), 7); print(drawing_ocr.run_baseline(t, Path(d), drawing_ocr.rapidocr_engine())["summary"])
PY
```
