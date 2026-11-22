package io.inhouse.erp.common;

import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Map;

/**
 * 사용자에게 보이는 문장을 만드는 도구: 받침에 맞춘 조사, 날짜 표기, 상태 표시 이름(ux/copy-guide.md).
 * 이름 뒤 조사를 "을"로 고정하면 "회의실 C을"처럼 틀리므로 끝 글자의 읽는 소리로 고릅니다.
 */
public final class Ko {

    private static final DateTimeFormatter WHEN = DateTimeFormatter.ofPattern("M월 d일 HH:mm");
    private static final DateTimeFormatter HOUR = DateTimeFormatter.ofPattern("HH:mm");
    /** 끝에 오는 따옴표·괄호·문장 부호는 건너뛰고 그 앞 글자로 받침을 봅니다. */
    private static final String SKIP = "'\"‘’“”)]}>」』.,!? ";
    /** 숫자를 읽을 때 받침: 영(ㅇ) 일(ㄹ) 이 삼(ㅁ) 사 오 육(ㄱ) 칠(ㄹ) 팔(ㄹ) 구. 값은 종성 번호(없음 0, ㄹ 8). */
    private static final int[] DIGIT = {21, 8, 0, 16, 0, 0, 1, 8, 8, 0};
    private static final int RIEUL = 8;

    private Ko() {}

    /** 을/를 */
    public static String eul(String word) {
        return word + (batchim(word) != 0 ? "을" : "를");
    }

    /** 이/가 */
    public static String i(String word) {
        return word + (batchim(word) != 0 ? "이" : "가");
    }

    /** 은/는 */
    public static String eun(String word) {
        return word + (batchim(word) != 0 ? "은" : "는");
    }

    /** 으로/로(ㄹ 받침은 "로") */
    public static String ro(String word) {
        int b = batchim(word);
        return word + (b != 0 && b != RIEUL ? "으로" : "로");
    }

    /** 끝 글자의 종성 번호(받침 없으면 0). 한글이 아닌 글자는 읽는 소리로 봅니다. */
    static int batchim(String word) {
        if (word == null) {
            return 0;
        }
        int i = word.length() - 1;
        while (i >= 0 && SKIP.indexOf(word.charAt(i)) >= 0) {
            i--;
        }
        if (i < 0) {
            return 0;
        }
        char c = word.charAt(i);
        if (c >= '가' && c <= '힣') {
            return (c - '가') % 28;
        }
        if (c >= '0' && c <= '9') {
            return DIGIT[c - '0'];
        }
        // 영문 이름 끝: 엘(L)·알(R)은 ㄹ, 엠(M)은 ㅁ, 엔(N)은 ㄴ. 나머지(에이, 비, 씨…)는 받침 없음
        return switch (Character.toUpperCase(c)) {
            case 'L', 'R' -> RIEUL;
            case 'M' -> 16;
            case 'N' -> 4;
            default -> 0;
        };
    }

    /** 목록·안내 날짜: 11월 21일 14:00 */
    public static String when(ZonedDateTime t) {
        return WHEN.format(t);
    }

    /** 같은 날이면 11월 21일 14:00~15:00, 날이 다르면 11월 21일 14:00 ~ 11월 22일 18:00 */
    public static String span(ZonedDateTime s, ZonedDateTime e) {
        return s.toLocalDate().equals(e.toLocalDate()) ? WHEN.format(s) + "~" + HOUR.format(e)
                : WHEN.format(s) + " ~ " + WHEN.format(e);
    }

    // ---------- 상태 표시 이름(코드 값은 화면에 내지 않음, copy-guide 1.1·1.5) ----------

    private static final Map<String, String> APPROVAL = Map.of(
            "in_progress", "진행 중", "approved", "승인", "rejected", "반려", "withdrawn", "회수");
    private static final Map<String, String> TICKET = Map.of(
            "open", "접수", "in_progress", "처리 중", "resolved", "해결", "closed", "종료", "cancelled", "취소");
    private static final Map<String, String> QUOTE = Map.of("draft", "초안", "issued", "발행", "cancelled", "취소");
    private static final Map<String, String> REPORT = Map.of("draft", "초안", "confirmed", "확정", "cancelled", "취소");
    private static final Map<String, String> DELEGATION = Map.of(
            "scheduled", "예정", "active", "대결 중", "expired", "종료", "revoked", "해제");

    public static String approvalStatus(String code) { return APPROVAL.getOrDefault(code, code); }
    public static String ticketStatus(String code) { return TICKET.getOrDefault(code, code); }
    public static String quoteStatus(String code) { return QUOTE.getOrDefault(code, code); }
    public static String reportStatus(String code) { return REPORT.getOrDefault(code, code); }
    public static String delegationStatus(String code) { return DELEGATION.getOrDefault(code, code); }
}
