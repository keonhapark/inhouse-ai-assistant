# ux

웹 재설계(#558)의 사용성 연구·평가를 둡니다. 화면 코드는 `web/`이 구현하고, 이 폴더는 고치지 않습니다. 실제 사용자 인터뷰 대신 에이전트·스크립트로 가상 사용자 평가를 하고, 결과마다 가상 사용자 결과라고 밝힙니다.

## 구성

| 경로 | 내용 |
|---|---|
| `research/` | 보고서. 시작은 [research/README.md](research/README.md) |
| `walkthrough/` | 페르소나 과업 걸어 보기 스크립트(Playwright) |
| `a11y/` | 화면별 axe-core 점검과 전체 화면 캡처 |
| `lib/serve.mjs` | web을 모의 데이터 모드로 빌드해 띄우는 정적 서버 |

## 실행

전체 스택(compose)은 띄우지 않습니다. web 모의 데이터 모드(msw)를 정적 빌드로 띄우고 브라우저 하나로 돌립니다. 메모리는 수백 MB면 됩니다.

```bash
cd ux
npm ci
npx playwright install --only-shell chromium   # 처음 한 번
npm --prefix ../web ci                          # web 빌드에 필요
npm run walk -- --label baseline                # → research/walkthrough/baseline/
npm run a11y -- --label baseline                # → research/a11y/baseline/
node research/wireframes/render.mjs             # 와이어프레임 PNG
```

- web 빌드는 `.cache/web-mock/`에 한 번 만들고 다시 씁니다. web이 바뀌었으면 `npm run walk -- --rebuild`로 다시 빌드합니다.
- 재설계 뒤 비교(#564)는 `--label after`처럼 다른 이름으로 돌려 같은 폴더 구조로 남깁니다.
