from harness.clarify import UNKNOWN_ANSWER, answer_for, looks_like_question

CL = [{"ifAskedAbout": ["날짜", "언제"], "answer": "다음 달 1일"}, {"ifAskedAbout": ["사유"], "answer": "병원"}]


def test_first_match_wins():
    assert answer_for("언제 쓰실 건지와 사유를 알려 주세요", CL) == ("다음 달 1일", True)


def test_no_match():
    assert answer_for("어느 회의실인가요?", CL) == (UNKNOWN_ANSWER, False)


def test_question_shape():
    assert looks_like_question("언제 쓰실 건가요?")
    assert looks_like_question("날짜를 알려 주시겠어요.")
    assert looks_like_question("휴가를 신청할까요")
    assert not looks_like_question("휴가를 신청했습니다.")


def test_question_list_ending_with_statement():
    text = ("반차 신청을 위해 확인이 필요합니다:\n\n1. **정확한 날짜**: 2027년 3월 9일(화)로 맞나요?\n"
            "2. **기간**: 하루 반차로 신청하시나요?\n\n이 정보를 알려주시면 바로 신청해 드리겠습니다.")
    assert looks_like_question(text)
    assert not looks_like_question("신청했습니다.\n결재선: 나우진 팀장")
