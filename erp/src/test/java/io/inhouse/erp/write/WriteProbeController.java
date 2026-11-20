package io.inhouse.erp.write;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.auth.RequiredScope;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.leave.LeaveBalance;
import io.inhouse.erp.leave.LeaveBalanceRepository;
import jakarta.servlet.http.HttpServletRequest;
import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 시험 전용 쓰기. 본인 연차 잔여의 pending에 days를 더합니다. 계약 경로가 아닙니다.
 * 되돌리기는 같은 만큼 뺍니다. pending이 그보다 작으면(그사이 바뀌었으면) undo-conflict입니다.
 */
@RestController
class WriteProbeController {

    static final String PATH = "/test-probe/pending";
    static final String IRREVERSIBLE_PATH = "/test-probe/pending-final";
    static final int YEAR = 2026;

    private final WriteExecutor writes;
    private final LeaveBalanceRepository balances;
    private final ObjectMapper mapper;

    WriteProbeController(WriteExecutor writes, LeaveBalanceRepository balances, ObjectMapper mapper) {
        this.writes = writes;
        this.balances = balances;
        this.mapper = mapper;
    }

    @PostMapping({PATH, IRREVERSIBLE_PATH})
    @RequiredScope("leave:read")
    ResponseEntity<Object> add(@AuthenticationPrincipal ErpPrincipal p,
                               @RequestParam(defaultValue = "false") boolean dryRun,
                               @RequestHeader(value = "Idempotency-Key", required = false) String key,
                               @RequestBody JsonNode body, HttpServletRequest http) {
        boolean undoable = http.getRequestURI().endsWith(PATH);
        WriteRequest req = WriteRequest.of(p, "probeAddPending", "leave_balance", http.getRequestURI(), body,
                dryRun, key);
        return writes.run(req, () -> {
            double days = body.path("days").asDouble(0);
            if (days <= 0) {
                throw ApiException.validation("days", "must be > 0");
            }
            LeaveBalance b = balances.findById(new LeaveBalance.Key(p.employeeId(), YEAR)).orElseThrow();
            JsonNode before = mapper.valueToTree(Map.of("pending", b.getAnnualPending()));
            b.addPending(BigDecimal.valueOf(days));
            JsonNode after = mapper.valueToTree(Map.of("pending", b.getAnnualPending()));
            return new WriteOutcome("pending에 " + days + "일을 더합니다",
                    List.of(new Change("update", "leave_balance", p.employeeId(), before, after),
                            new Change("create", "probe_note", "note_" + p.employeeId(), null, after)),
                    undoable, after, p.employeeId(), null, null);
        });
    }

    @Component
    static class Undo implements UndoHandler {
        private final LeaveBalanceRepository balances;
        private final ObjectMapper mapper;

        Undo(LeaveBalanceRepository balances, ObjectMapper mapper) {
            this.balances = balances;
            this.mapper = mapper;
        }

        @Override
        public String operation() {
            return "probeAddPending";
        }

        @Override
        public WriteOutcome undo(Action original) {
            LeaveBalance b = balances.findById(new LeaveBalance.Key(original.getResourceId(), YEAR)).orElseThrow();
            BigDecimal one = BigDecimal.ONE;
            if (b.getAnnualPending().compareTo(one) < 0) {
                throw new ApiException(409, "undo-conflict", "pending이 그사이 줄었습니다");
            }
            b.addPending(one.negate());
            JsonNode after = mapper.valueToTree(Map.of("pending", b.getAnnualPending()));
            return WriteOutcome.of("pending에서 1일을 뺍니다", new Change("update", "leave_balance",
                    original.getResourceId(), null, after), false, after, original.getResourceId());
        }
    }
}
