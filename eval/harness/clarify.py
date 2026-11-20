"""되묻기 응답: 시나리오에 미리 쓴 답 스크립트로 답합니다."""

from __future__ import annotations

from typing import Any

UNKNOWN_ANSWER = "모르겠습니다"

# 에이전트 답이 되묻기인지 보는 끝말. 계약에 되묻기 표시가 없어 답 끝 모양으로 봅니다.
_QUESTION_ENDINGS = ("?", "？", "까요", "나요", "가요", "습니까", "십니까", "주세요", "주시겠어요")


def looks_like_question(text: str) -> bool:
    t = text.strip().rstrip(".!~ ")
    return t.endswith(_QUESTION_ENDINGS)


def answer_for(question: str, clarifications: list[dict[str, Any]]) -> tuple[str, bool]:
    """처음 맞는 항목의 답과 True를, 맞는 것이 없으면 UNKNOWN_ANSWER와 False를 돌려줍니다."""
    for c in clarifications:
        if any(word in question for word in c["ifAskedAbout"]):
            return c["answer"], True
    return UNKNOWN_ANSWER, False
