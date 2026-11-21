# 영수증 전통 기준선: RapidOCR + 정규식(개발 묶음, #463)

가짜 영수증 개발 묶음 40장(#462, `receipts/dev-truth.jsonl`)을 CPU OCR(RapidOCR 한국어 모델)로 읽고, 정규식(`harness/receipt_baseline.py`)으로 금액·날짜·가맹점·사업자번호를 뽑아 필드 완전 일치(`harness/receipts.py`)로 셌습니다. 비전 모델(로컬 Qwen3.5-9B 등)과 같은 묶음·같은 채점기로 견줄 바닥값입니다.

## 조건

- OCR: rapidocr 3.10.0(Apache-2.0), onnxruntime 1.32.0 CPU, 검출 PP-OCRv6_det_small, 인식 korean_PP-OCRv5_rec_mobile. 저장소 밖 가상환경. tesseract는 이 PC에 설치 권한이 없어 쓰지 않았습니다.
- 그림: `tools/make_receipts.py` 개발 시드, 글꼴 Noto Sans KR(SIL OFL, 저장소에 넣지 않음)
- 기기: 데스크탑 WSL2 CPU, 40장 41.9초(정상 셋 v2 측정이 끝난 뒤, GPU 쓰지 않음)
- **정규식은 이 개발 묶음 결과를 보고 한 번 고쳤습니다.** 처음 규칙(합계 줄의 마지막 금액)은 기운 영수증에서 라벨과 금액이 다른 줄로 묶여 부가세를 골랐습니다. "합계가 가장 큰 금액"으로 바꾸고 가맹점 후보에서 날짜 라벨 줄을 뺐습니다. 기획서대로 기준선에도 다듬을 기회를 한 번 줬고, 확인 묶음(다른 시드)은 이 규칙을 고정해 한 번만 돕니다.

## 결과(40장)

| 필드 | 고치기 전 | 고친 뒤 |
|---|---|---|
| 금액 | 29 | 38 (95.0%, 83.1%~99.4%) |
| 날짜 | 35 | 35 (87.5%, 73.2%~95.8%) |
| 가맹점 | 27 | 27 (67.5%, 50.9%~81.4%) |
| 사업자번호 | 39 | 39 (97.5%, 86.8%~99.9%) |
| 네 필드 모두 | 17 (42.5%) | 24 (60.0%, 43.3%~75.1%) |

고친 뒤 묶음별(네 필드 모두): 왜곡 약함 6/9, 강함(기울기 4° 이상·흐림 1 이상·구김 2) 18/31. 레이아웃 카드 전표 10/16, 마트 3/6, 음식점 11/18(실행 기록 `2026-11-22-ocr-rapidocr-dev.json`의 `summary.groups`).

- **가맹점이 가장 약합니다.** 틀린 13장 모두 OCR 줄에 가맹점 이름이 그대로 나오지 않았습니다(줄을 놓치거나 글자를 틀림, 같은 그림을 다시 읽어 확인). 정규식으로는 더 고칠 수 없는 부분입니다.
- 날짜 5장은 구김이 심해 숫자가 깨진 경우(예: `2026.1D.27`)입니다.
- OCR이 완벽할 때의 정규식 상한(oracle)은 40/40입니다.

## 다시 재는 방법

```
uv run --group tools python tools/make_receipts.py --out ~/data/receipts-dev --font <NotoSansKR-Regular.ttf>
PYTHONPATH=. ~/.cache/iaa-ocr-venv/bin/python tools/ocr_baseline.py --images ~/data/receipts-dev --engine rapidocr --out <결과 이름>
```
