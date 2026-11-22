"""#427 측정: 외부 별칭 요청을 로컬로 돌릴 때 reasoning_effort none(생각 끔)을 채운 경우와 채우지 않은 경우의 응답 시간.

gateway가 로컬로 돌린 호출과 같은 모양(시스템 프롬프트 + 도구 두 개 + 사용자 질문)을 LiteLLM 1.108.1(`ollama_chat/qwen3.5:9b`,
num_ctx 8192, gateway/litellm/config.yaml의 local과 같은 설정)로 보냅니다. 질문마다 두 조건을 번갈아 보내 순서 효과를 줄이고,
처음 한 번은 모델 적재용으로 버립니다. 질문은 지어낸 것입니다.

    cd gateway && uv run --with litellm==1.108.1 --with mcp python bench/reroute_latency.py [--reps 3] [--device "코랩 T4, 터널 경유"]
"""

from __future__ import annotations

import argparse
import statistics
import time

import litellm

from colab import base_url, meta, save

SYSTEM = "당신은 사내 비서입니다. 오늘은 2027-03-08입니다. 필요하면 도구를 부르고, 아니면 한국어로 짧게 답합니다."
TOOLS = [
    {"type": "function", "function": {"name": "search_docs", "description": "사내 규정 문서를 찾습니다.",
                                      "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                                                     "required": ["query"]}}},
    {"type": "function", "function": {"name": "leave_request", "description": "휴가 결재를 올립니다.",
                                      "parameters": {"type": "object", "properties": {
                                          "start": {"type": "string"}, "end": {"type": "string"},
                                          "reason": {"type": "string"}}, "required": ["start", "end"]}}},
]
QUESTIONS = [
    "출장비 규정에서 숙박비 한도가 얼마야?",
    "2027년 3월 11일 병가 하루 신청해 줘. 감기가 심해서요.",
    "팀장님께 보낼 주간 보고 첫 문장을 공손하게 다듬어 줘: 이번 주 일정이 밀렸습니다.",
    "연차와 반차의 차이를 두 문장으로 설명해 줘.",
    "다음 주 월요일부터 수요일까지 휴가 내 줘. 가족 행사야.",
]


def call(url: str, question: str, effort: str | None) -> dict:
    kw = {"reasoning_effort": effort} if effort else {}
    t0 = time.monotonic()
    try:
        r = litellm.completion(model="ollama_chat/qwen3.5:9b", api_base=url, num_ctx=8192, timeout=180,
                               messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}],
                               tools=TOOLS, **kw)
    except Exception as e:  # 시간 초과도 결과로 남깁니다
        return {"seconds": round(time.monotonic() - t0, 2), "error": f"{type(e).__name__}: {str(e)[:160]}"}
    m = r.choices[0].message
    return {"seconds": round(time.monotonic() - t0, 2), "completionTokens": r.usage.completion_tokens,
            "toolCall": bool(m.tool_calls), "reasoningChars": len(getattr(m, "reasoning_content", None) or "")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url")
    ap.add_argument("--device", default="코랩 T4, 터널 경유")
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()
    url = base_url(args.base_url)
    warm = call(url, "안녕", "none")   # 적재용, 버림
    if "error" in warm:
        raise SystemExit(f"적재 호출 실패: {warm['error']}")
    rows = []
    for rep in range(args.reps):
        for qi, q in enumerate(QUESTIONS):
            order = ("none", None) if (rep + qi) % 2 == 0 else (None, "none")
            for effort in order:
                row = {"rep": rep, "question": qi, "effort": effort or "(없음, 모델 기본=생각)", **call(url, q, effort)}
                rows.append(row)
                print(row, flush=True)

    def summary(effort_label):
        xs = [r for r in rows if r["effort"] == effort_label]
        ok = [r["seconds"] for r in xs if "error" not in r]
        return {"n": len(xs), "errors": sum("error" in r for r in xs), "over60s": sum(r["seconds"] > 60 for r in xs),
                "median": statistics.median(ok) if ok else None, "max": max(ok) if ok else None,
                "mean": round(statistics.mean(ok), 2) if ok else None,
                "medianCompletionTokens": statistics.median([r["completionTokens"] for r in xs if "error" not in r]) if ok else None}

    out = {"meta": meta(args.device, model="ollama_chat/qwen3.5:9b (Q4_K_M)", litellm="1.108.1", reps=args.reps,
                        questions=len(QUESTIONS), timeoutSeconds=180),
           "summary": {"none": summary("none"), "default": summary("(없음, 모델 기본=생각)")}, "rows": rows}
    path = save("reroute-latency.json", out)
    print("요약:", out["summary"])
    print("저장:", path.name)


if __name__ == "__main__":
    main()
