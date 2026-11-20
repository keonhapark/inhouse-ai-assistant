# erp 동시 예약·동시 결재 부하 시험

같은 자원에 요청이 몰릴 때 규칙이 지켜지는지(하나만 성공, 나머지는 정해진 409, 5xx 없음), 그리고 그때의 처리량과 지연을 잽니다. 스크립트는 `load.py`, 결과 원본은 `results/run-*.json`입니다.

## 다시 재는 방법

```bash
# 저장소 루트에서
bash scripts/dev-keys.sh                       # 처음 한 번
export ERP_DEMO_PASSWORD=demo ERP_JWT_SECRET=$(openssl rand -hex 32) \
       DELEGATION_TOKEN_PUBLIC_KEY=$PWD/infra/dev-keys/delegation-es256.pub.pem
ERP_PORT=8140 ERP_PG_PORT=8160 bash erp/ci/start.sh
cd contracts
for i in 1 2 3; do
  uv run python ../erp/bench/load.py --base http://localhost:8140/api/v1 \
    --concurrency 50 --rounds 20 --out ../erp/bench/results/run-$i.json
done
cd .. && ERP_PORT=8140 bash erp/ci/stop.sh
```

- 규칙 위반이나 5xx가 하나라도 있으면 스크립트가 종료 코드 1로 끝납니다.
- 회의실 날짜는 실행마다 무작위로 멀리(2,000일 뒤 이후) 잡으므로 같은 erp에 여러 번 돌려도 겹치지 않습니다. 결재 시나리오는 실행마다 지출 결재 문서 1,020개를 새로 만듭니다.
- 도구: Python 3 asyncio + httpx 0.28.1(`contracts/uv.lock`). k6·wrk 같은 별도 도구 없이 저장소 의존성만으로 다시 잴 수 있게 했습니다.

## 시나리오

| 시나리오 | 무엇을 | 규칙(위반으로 셈) |
|---|---|---|
| `room_contention` | 같은 회의실·같은 30분에 동시 예약 50건 × 20라운드 | 라운드마다 201 정확히 1건, 나머지 409 `room-conflict` |
| `room_throughput` | 일꾼 50개가 서로 겹치지 않는 예약을 20건씩(1,000건) | 모두 201 |
| `approval_contention` | 지출 결재 1건을 올리고 결재자가 같은 version으로 동시 승인 50건 × 20라운드 | 라운드마다 201 정확히 1건, 나머지 409 `version-conflict` 또는 `invalid-state` |
| `approval_throughput` | 미리 올린 서로 다른 문서 1,000개를 일꾼 50개가 동시에 승인 | 모두 201 |

`approval_contention`의 409는 두 가지입니다. 같은 순간 커밋을 다투다 진 요청은 `version-conflict`(낙관적 락)이고, 승인이 커밋된 뒤 문서를 읽은 요청은 문서가 이미 끝났으므로 `invalid-state`입니다.

## 조건

- 측정: 2026-11-20 23:06~23:07 KST, Apple M1 Pro 32GB, macOS(Darwin 25.5.0)
- erp: `erp/ci/start.sh`(bootJar, JVM 기본 옵션, Tomcat 기본 스레드 200, HikariCP 기본 풀 10), PostgreSQL 16(docker `postgres:16-alpine`), 같은 기기
- 부하 생성기도 같은 기기에서 돌았습니다. 측정 동안 다른 개발 세션들이 함께 떠 있었고 load average가 약 10이었습니다. 지연 절댓값은 이 기기 상태에 묶인 값이고, 실행 사이 흔들림도 큽니다(아래 3회 범위)
- 로그인은 시나리오 전에 미리 해 두고 지연에 넣지 않았습니다

## 결과(3회)

| 시나리오 | 요청 | 처리량(요청/초) | p50 ms | p95 ms | p99 ms | 최대 ms | 위반 | 5xx |
|---|---|---|---|---|---|---|---|---|
| room_contention | 1,000 × 3 | 154 / 202 / 175 | 164 / 142 / 157 | 355 / 237 / 289 | 482 / 260 / 347 | 522 / 300 / 382 | 0 | 0 |
| room_throughput | 1,000 × 3 | 193 / 260 / 222 | 136 / 110 / 120 | 776 / 547 / 619 | 1,171 / 879 / 955 | 2,119 / 1,330 / 1,367 | 0 | 0 |
| approval_contention | 1,000 × 3 | 227 / 210 / 188 | 110 / 114 / 141 | 230 / 293 / 247 | 354 / 333 / 268 | 406 / 363 / 315 | 0 | 0 |
| approval_throughput | 1,000 × 3 | 211 / 239 / 225 | 145 / 138 / 145 | 707 / 598 / 704 | 1,137 / 895 / 1,024 | 2,005 / 1,752 / 1,638 | 0 | 0 |

- 12,000건 모두 규칙대로 끝났습니다. 경쟁 라운드 120번(회의실 60, 결재 60) 모두 성공이 정확히 1건이었고 5xx는 없었습니다.
- `approval_contention`의 409 2,940건 중 `version-conflict` 150건, `invalid-state` 2,790건입니다.
- 같은 회의실 동시 예약은 이 측정 전(#120 수정 전)에는 PostgreSQL 배제 제약끼리의 교착으로 500이 섞였습니다(동시 7건 × 30회 중 19회). 지금은 회의실 행을 먼저 잠가 줄 세웁니다(`RoomRepository.lockById`).
- 처리량 시나리오의 꼬리 지연(p99 약 0.9~1.2초)은 동시 50건이 DB 연결 풀 10개를 기다리는 시간으로 봅니다. 풀 크기를 바꿔 다시 재지는 않았습니다.
