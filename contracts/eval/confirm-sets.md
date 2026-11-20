# 확인 셋 해시

확인 셋 원문은 저장소 밖에 둡니다(`eval/protocol.md` 7절). 첫 실행 전에 묶음 해시만 여기에 남깁니다. 보고서는 실행한 묶음의 해시가 이 표와 같은지 적습니다.

해시 계산: 묶음 manifest의 `files`를 경로 순으로 `<sha256>  <경로>` 줄로 이어 붙인 문자열의 SHA-256입니다.

| 묶음 | 쓰임 | 구성 | bundleSha256 | 커밋한 날 |
|---|---|---|---|---|
| confirm-v1 | 1단계 주 결과(사고율) | 75개: 작성자 gemini·agentdojo·generator 각 25 | `4b52309174275eb3421dc857615b48ae4f70e44e36ae06831c13ecc847abae63` | 2026-11-21 |
| toolcall-v1 | #103 도구 호출 측정 주 결과 | 120개: 1단계 도구 15·2단계 도구 2, 도구마다 7개 이상. direct 47, confusable 32, resolve 23, clarify 18 | `bf7066b5b7c5794836ec875ac1b4139b47b00a3693c5f60c3fafce2e0cdd123e` | 2026-11-21 |
