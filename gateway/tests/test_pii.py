import pytest

from gateway.pii import KoreanRedactor


@pytest.fixture(scope="module")
def r():
    return KoreanRedactor()


@pytest.mark.parametrize("text,label", [
    ("주민번호 900101-1234568 확인", "[주민등록번호]"),          # 검증 숫자 맞음
    ("주민등록번호는 0501013123456입니다", "[주민등록번호]"),      # 2020년 뒤 발급처럼 검증 숫자가 틀려도 날짜가 맞으면 가림
    ("연락처 010-1234-5678로", "[전화번호]"),
    ("휴대폰 01012345678", "[전화번호]"),
    ("+82 10-1234-5678", "[전화번호]"),
    ("사무실 02-123-4567", "[전화번호]"),
    ("급여 계좌 110-123-456789", "[계좌번호]"),
    ("국민은행 123456-01-234567로 입금", "[계좌번호]"),
    ("사업자등록번호 220-81-62517", "[사업자등록번호]"),
    ("운전면허 11-12-123456-12", "[운전면허번호]"),
    ("여권번호 M12345678", "[여권번호]"),
    ("메일 hong.gil@example.co.kr로 보내 주세요", "[이메일]"),
    ("카드 4111-1111-1111-1111", "[카드번호]"),
])
def test_detects(r, text, label):
    out = r.redact_text(text)
    assert label in out.text, out.text
    assert sum(out.counts.values()) == 1


@pytest.mark.parametrize("text", [
    "회의는 2026-11-20 14:00에 합니다",          # 날짜
    "주문번호 1234567890 확인",                    # 문맥 없는 숫자열
    "번호 991332-1234567",                         # 없는 날짜(13월 32일)
    "사업자번호 123-45-67890",                     # 검증 숫자 틀림
    "버전 1.108.1, 포트 8210",
    "M12345678 모델 부품",                         # 문맥 없는 여권 모양
    "회의실 3층 301호, 4명",
])
def test_leaves_non_pii(r, text):
    out = r.redact_text(text)
    assert out.text == text and not out.counts


def test_body_redaction_keeps_shape(r):
    body = {"model": "external", "temperature": 0, "messages": [
        {"role": "system", "content": "도우미입니다"},
        {"role": "user", "content": [{"type": "text", "text": "전화 010-2222-3333"},
                                     {"type": "image_url", "image_url": {"url": "data:,"}}]},
        {"role": "user", "content": "메일 a@b.io, 전화 010-4444-5555"},
    ]}
    sent, counts = r(body)
    assert sent["temperature"] == 0 and sent["messages"][0]["content"] == "도우미입니다"
    assert sent["messages"][1]["content"][0]["text"] == "전화 [전화번호]"
    assert sent["messages"][1]["content"][1] == body["messages"][1]["content"][1]
    assert sent["messages"][2]["content"] == "메일 [이메일], 전화 [전화번호]"
    assert counts == {"KR_PHONE": 2, "EMAIL_ADDRESS": 1}
    assert body["messages"][2]["content"] == "메일 a@b.io, 전화 010-4444-5555"  # 원본은 그대로
