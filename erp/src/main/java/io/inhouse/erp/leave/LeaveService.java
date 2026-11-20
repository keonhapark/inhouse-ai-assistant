package io.inhouse.erp.leave;

import io.inhouse.erp.common.ApiException;
import java.math.BigDecimal;
import java.time.Clock;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Optional;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 연차 잔여. 직원마다 가장 최근 연도의 잔여 하나를 씁니다(연도 넘김은 팩 고정 데이터에서 다룸).
 * 결재 중이면 pending, 최종 승인되면 used로 옮깁니다.
 */
@Service
public class LeaveService {

    public record BalanceView(String employeeId, int year, BigDecimal annualTotal, BigDecimal annualUsed,
                              BigDecimal annualPending, BigDecimal annualRemaining) {}

    private static final BigDecimal HALF = new BigDecimal("0.5");

    private final LeaveBalanceRepository repo;
    private final Clock clock;

    public LeaveService(LeaveBalanceRepository repo, Clock clock) {
        this.repo = repo;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public BalanceView view(String employeeId) {
        return latest(employeeId).map(LeaveService::view).orElseGet(() -> new BalanceView(employeeId,
                LocalDate.now(clock).getYear(), BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO));
    }

    private static BalanceView view(LeaveBalance b) {
        return new BalanceView(b.getEmployeeId(), b.getYear(), b.getAnnualTotal(), b.getAnnualUsed(),
                b.getAnnualPending(), b.remaining());
    }

    /**
     * 휴가 일수. 연차는 시작~끝의 평일 수, 반차는 0.5(하루만), 그 밖의 휴가(병가·경조사)는 연차에서 빼지 않습니다.
     */
    public static BigDecimal days(String leaveType, String start, String end) {
        LocalDate s = date("start_date", start);
        LocalDate e = date("end_date", end);
        if (e.isBefore(s)) {
            throw formError("end_date", "before start_date", "end_date가 start_date보다 앞입니다");
        }
        if ("half_am".equals(leaveType) || "half_pm".equals(leaveType)) {
            if (!s.equals(e)) {
                throw formError("end_date", "must equal start_date", "반차는 하루만 씁니다");
            }
            return HALF;
        }
        if (!"annual".equals(leaveType)) {
            return BigDecimal.ZERO;
        }
        long weekdays = s.datesUntil(e.plusDays(1))
                .filter(d -> d.getDayOfWeek() != DayOfWeek.SATURDAY && d.getDayOfWeek() != DayOfWeek.SUNDAY)
                .count();
        return BigDecimal.valueOf(weekdays);
    }

    /** 결재를 올릴 때: 잔여를 확인하고 pending(결재선이 없으면 used)에 더합니다. 잔여 행을 잠가 동시 상신이 넘치지 않게 합니다. */
    public void reserve(String employeeId, BigDecimal days, boolean immediatelyApproved) {
        if (days.signum() == 0) {
            return;
        }
        LeaveBalance b = locked(employeeId).orElse(null);
        BigDecimal remaining = b == null ? BigDecimal.ZERO : b.remaining();
        if (days.compareTo(remaining) > 0) {
            throw new ApiException(422, "leave-balance-insufficient",
                    "필요 " + days.stripTrailingZeros().toPlainString() + "일, 남은 "
                            + remaining.stripTrailingZeros().toPlainString() + "일");
        }
        if (immediatelyApproved) {
            b.addUsed(days);
        } else {
            b.addPending(days);
        }
    }

    /** 반려·회수: pending에서 뺍니다. */
    public void release(String employeeId, BigDecimal days) {
        locked(employeeId).ifPresent(b -> b.addPending(days.negate()));
    }

    /** 최종 승인: pending에서 used로 옮깁니다. */
    public void commit(String employeeId, BigDecimal days) {
        locked(employeeId).ifPresent(b -> {
            b.addPending(days.negate());
            b.addUsed(days);
        });
    }

    /** 승인된 휴가를 회수: used에서 뺍니다. */
    public void restore(String employeeId, BigDecimal days) {
        locked(employeeId).ifPresent(b -> b.addUsed(days.negate()));
    }

    private Optional<LeaveBalance> latest(String employeeId) {
        return repo.findByEmployeeIdOrderByYearDesc(employeeId).stream().findFirst();
    }

    private Optional<LeaveBalance> locked(String employeeId) {
        List<LeaveBalance> rows = repo.lockByEmployee(employeeId);
        return rows.stream().findFirst();
    }

    public static LocalDate date(String field, String value) {
        try {
            return LocalDate.parse(value);
        } catch (DateTimeParseException | NullPointerException e) {
            throw formError(field, "YYYY-MM-DD", field + ": 날짜 형식이 아닙니다");
        }
    }

    private static ApiException formError(String field, String message, String detail) {
        return new ApiException(422, "form-validation-failed", detail, List.of(new ApiException.FieldError(field, message)));
    }
}
