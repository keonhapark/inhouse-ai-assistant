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
