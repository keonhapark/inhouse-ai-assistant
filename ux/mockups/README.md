# 방향별 고충실도 정적 시안(#568)

디자인 시스템 명세(#563) 전에 사용자가 실제 화면을 보고 방향을 고르도록 만든 정적 시안입니다. 비교 페이지는 [index.html](index.html)입니다.

| 방향 | 폴더 | 레퍼런스 묶음(`../research/references.md` 2절) |
|---|---|---|
| 섞음(추천) | `mixed/` | Linear식 셸 + Geist식 토큰 + Ramp식 경비·결재 |
| 운영 도구형 | `ops/` | Linear + Geist + Carbon |
| 대화 비서형 | `assistant/` | Fluent 2 + Ramp + Geist |

- 방향마다 화면 두 개: AI 비서(`chat`)와 결재(`approvals`). 밝은 테마만 있습니다.
- 구조는 `../research/ia.md` 2절(왼쪽 탐색 막대 업무·회사, 첫 화면 안 A)을 따릅니다. 운영 묶음 메뉴는 감사 권한이 있을 때만 보여, 직원·팀장 화면인 이 시안에는 없습니다.
- 데이터는 지어낸 회사(한결정밀)와 사람입니다. 사업자번호는 예시 번호입니다. 영수증 그림도 직접 그린 SVG입니다.
- 남의 제품 화면을 베끼지 않았습니다. 레퍼런스에서는 규칙과 패턴만 가져왔습니다.
- web 코드와 의존성은 건드리지 않습니다. 고른 방향은 #563 명세를 거쳐 web이 구현합니다.

## 구성

| 경로 | 내용 |
|---|---|
| `src/data.mjs` | 가상 데이터 |
| `src/templates.mjs` | 화면 HTML 조각(세 방향 공용, 방향별 배치 변형) |
| `src/base.css` | 공용 구조. 값은 모두 토큰 변수 |
| `<방향>/tokens.css` | 방향별 토큰(이름은 세 방향이 같고 값만 다름). `UI Designer` 에이전트가 초안을 잡음 |
| `<방향>/direction.css` | 방향별 배치·마감 |
| `<방향>/*.html`, `*.png` | 만든 시안과 1440×900 그림 |

## 다시 만들기

```bash
cd ux
npm ci
npm --prefix ../web ci          # 그림을 찍을 때 Pretendard 글꼴 파일을 씀
npm run mockups                 # HTML 생성 + PNG 촬영
```

HTML은 빌드 도구 없이 브라우저로 바로 엽니다. 서체는 jsDelivr의 Pretendard를 불러옵니다.

## 라이선스

- 서체: Pretendard(SIL OFL 1.1)
- 아이콘: Lucide(ISC), `lucide-static`에서 SVG를 인라인으로 넣음
