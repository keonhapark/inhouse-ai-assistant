package io.inhouse.erp.common;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.ZoneId;
import java.time.ZonedDateTime;
import org.junit.jupiter.api.Test;

class KoTest {

    @Test
    void particleFollowsLastSound() {
        // 한글 받침
        assertThat(Ko.eul("대회의실")).isEqualTo("대회의실을");
        assertThat(Ko.eul("경비 정산")).isEqualTo("경비 정산을");
        assertThat(Ko.eul("휴가")).isEqualTo("휴가를");
        // 영문 끝: 씨(C)는 받침 없음, 엘(L)·엠(M)·엔(N)·알(R)은 받침
        assertThat(Ko.eul("회의실 C")).isEqualTo("회의실 C를");
        assertThat(Ko.eun("회의실 C")).isEqualTo("회의실 C는");
        assertThat(Ko.eun("회의실 M")).isEqualTo("회의실 M은");
        // 숫자는 읽는 소리: 삼(ㅁ) 이(없음) 육(ㄱ) 칠(ㄹ)
        assertThat(Ko.eul("3층")).isEqualTo("3층을");
        assertThat(Ko.eul("회의실 3")).isEqualTo("회의실 3을");
        assertThat(Ko.eul("회의실 2")).isEqualTo("회의실 2를");
        assertThat(Ko.i("E0036")).isEqualTo("E0036이");
        assertThat(Ko.i("E0032")).isEqualTo("E0032가");
        // 따옴표·괄호는 건너뛰고 그 안 끝 글자로
        assertThat(Ko.eul("'출장비 정산'")).isEqualTo("'출장비 정산'을");
        assertThat(Ko.eul("'노트북 교체'")).isEqualTo("'노트북 교체'를");
        // 괄호로 끝나면 괄호 앞 말에 맞춤
        assertThat(Ko.wa("수량 × 단가(5,000원)")).isEqualTo("수량 × 단가(5,000원)와");
        assertThat(Ko.eul("'VPN 오류(재발)'")).isEqualTo("'VPN 오류(재발)'를");
        assertThat(Ko.wa("합계")).isEqualTo("합계와");
        assertThat(Ko.wa("금액")).isEqualTo("금액과");
    }

    @Test
    void latinWordsUseEndSoundAndInitialismsUseLetterNames() {
        assertThat(Ko.eul("'Printer'")).isEqualTo("'Printer'를");
        assertThat(Ko.eul("Server")).isEqualTo("Server를");
        assertThat(Ko.eul("Outlook")).isEqualTo("Outlook을");
        assertThat(Ko.eul("Slack")).isEqualTo("Slack을");
        assertThat(Ko.eul("Internet")).isEqualTo("Internet을");
        assertThat(Ko.eul("Chrome")).isEqualTo("Chrome을");
        assertThat(Ko.eul("Office")).isEqualTo("Office를");
        assertThat(Ko.eul("Excel")).isEqualTo("Excel을");
        assertThat(Ko.ro("Excel")).isEqualTo("Excel로");
        assertThat(Ko.eul("VPN")).isEqualTo("VPN을");
        assertThat(Ko.eul("PC")).isEqualTo("PC를");
    }

    @Test
    void roUsesRoAfterRieulOrVowel() {
        assertThat(Ko.ro("처리 중")).isEqualTo("처리 중으로");
        assertThat(Ko.ro("해결")).isEqualTo("해결로");
        assertThat(Ko.ro("종료")).isEqualTo("종료로");
        assertThat(Ko.ro("접수")).isEqualTo("접수로");
    }

    @Test
    void datesAreMonthDayAndTime() {
        ZoneId z = ZoneId.of("Asia/Seoul");
        ZonedDateTime s = ZonedDateTime.of(2026, 11, 21, 14, 0, 0, 0, z);
        assertThat(Ko.when(s)).isEqualTo("11월 21일 14:00");
        assertThat(Ko.span(s, s.plusHours(1))).isEqualTo("11월 21일 14:00~15:00");
        assertThat(Ko.span(s, s.plusDays(1).plusHours(4))).isEqualTo("11월 21일 14:00 ~ 11월 22일 18:00");
        ZonedDateTime dec = ZonedDateTime.of(2026, 12, 28, 9, 0, 0, 0, z);
        assertThat(Ko.span(dec, dec.plusDays(6))).isEqualTo("2026년 12월 28일 09:00 ~ 2027년 1월 3일 09:00");
    }

    @Test
    void statusCodesBecomeDisplayNames() {
        assertThat(Ko.approvalStatus("in_progress")).isEqualTo("진행 중");
        assertThat(Ko.ticketStatus("closed")).isEqualTo("종료");
        assertThat(Ko.quoteStatus("issued")).isEqualTo("발행");
        assertThat(Ko.reportStatus("confirmed")).isEqualTo("확정");
        assertThat(Ko.delegationStatus("revoked")).isEqualTo("해제");
        assertThat(Ko.ticketStatus("unknown")).isEqualTo("unknown");
    }
}
