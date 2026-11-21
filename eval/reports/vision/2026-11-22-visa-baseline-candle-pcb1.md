# 불량 사진 전통 기준선: VisA candle·pcb1(#495, #110)

기획서 측정 설계의 불량 사진 기준선(지도 분류기·이상 탐지)입니다. VisA(CC BY 4.0) 두 범주를 저장소 밖에 받아, CPU 손 특징(64×64 회색 화소·색 히스토그램·기울기 히스토그램)과 최근접 이웃으로 불량 유형 분류와 이상 탐지를 쟀습니다(`tools/visa_baseline.py`). 학습 없는 손 특징이라 비전 모델과 견줄 바닥값입니다.

## 조건

- 데이터: VisA `VisA_20220922.tar`에서 `tools/fetch_visa.py --classes candle,pcb1 --per-class 40 --normal-per-class 40`. 범주마다 묶음 순서로 처음 나온 불량 40장·정상 40장입니다(무작위 추출이 아님). 사진은 저장소 밖(`~/data/visa-subset`, 30MB), manifest sha256 앞 12자 `46f20fde3ff4`
- 나누기: 범주마다 정상·불량을 각각 반씩 학습·시험(시드 7). 불량 유형은 `image_anno.csv`의 `label`(여러 개면 첫째)
- 이상 탐지 문턱: 학습 정상끼리(한 장 뺀) 최근접 거리의 95번째 백분위
- 기기: 데스크탑 WSL2 CPU, 5.4초(GPU 쓰지 않음)

## 결과

| 지표 | 값 |
|---|---|
| 불량 유형 분류(1-NN) | 19/40 (47.5%, 31.5%~63.9%) |
| 참고: 가장 흔한 유형만 답함 | 9/40 (22.5%, 10.8%~38.5%) |
| 이상 탐지 재현율(불량을 불량으로) | 17/40 (42.5%, 27.0%~59.1%) |
| 이상 탐지 거짓 경보(정상을 불량으로) | 5/40 (12.5%, 4.2%~26.8%) |
| 이상 탐지 정확도 | 52/80 (65.0%, 53.5%~75.3%) |

| 범주 | 정상 | 불량 | 불량 유형 | 유형 분류 | AUROC |
|---|---|---|---|---|---|
| candle | 40 | 40 | chunk of wax missing 6, damaged corner of packaging 9, different colour spot 9, extra wax in candle 3, foreign particals on candle 4, wax melded out of the candle 4, weird candle wick 5 | 9/20 (45.0%, 23.1%~68.5%) | 0.925 |
| pcb1 | 40 | 40 | bent 8, melt 17, missing 9, scratch 6 | 10/20 (50.0%, 27.2%~72.8%) | 0.718 |

## 읽는 법

- **불량 유형 분류는 47.5%로, 가장 흔한 유형만 답하는 기준(22.5%)보다 높지만 절반 아래입니다.** candle은 유형이 7가지, pcb1은 4가지이고 시험 사진이 범주마다 20장이라 구간이 넓습니다.
- **이상 탐지는 순위로는 candle이 잘 가르고(AUROC 0.925) pcb1은 약합니다(0.718).** 문턱 판정은 거짓 경보를 12.5%로 묶는 대신 불량의 42.5%만 잡았습니다. 문턱을 낮추면 재현율과 거짓 경보가 함께 오릅니다.
- 비전 모델과 견줄 때는 같은 사진·같은 나누기로 시험 절반만 씁니다. 지금 이미지 채점기(`harness/vision.py`)의 불량 유형 어휘는 합성 사진용 네 가지(긁힘·찍힘·균열·변색)라, VisA 유형 설명으로 채점하려면 어휘를 더해야 합니다.

## 다시 재는 방법

```
uv run python tools/fetch_visa.py --out ~/data/visa-subset --classes candle,pcb1 --per-class 40 --normal-per-class 40
uv run --group tools python tools/visa_baseline.py --data ~/data/visa-subset --out <결과 이름> --seed 7
```

VisA 출처: Zou et al., "SPot-the-Difference Self-Supervised Pre-training for Anomaly Detection and Segmentation"(ECCV 2022), https://github.com/amazon-science/spot-diff , CC BY 4.0.
