package io.inhouse.erp.eval;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.ApiTestBase;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders;

@TestPropertySource(properties = "erp.eval-reset=1")
class EvalResetTest extends ApiTestBase {

    private int reset() throws Exception {
        return mvc.perform(MockMvcRequestBuilders.post("/_eval/reset")).andReturn().getResponse().getStatus();
    }

    /** 사람마다 시작 상태를 비교할 조회들. */
    private List<JsonNode> snapshot(String emp, String leader, String auditor) throws Exception {
        return List.of(json(get("/leave/balance", emp)), json(get("/approval-documents", emp, "box", "outbox")),
                json(get("/approval-documents", leader, "box", "inbox")), json(get("/delegations", leader, "role",
                        "delegator")), json(get("/room-reservations", emp, "mine", "false")),
                json(get("/notifications", leader)), json(get("/audit-events", auditor, "limit", "500")));
    }

    @Test
    void resetRestoresPackStartState() throws Exception {
        String emp = members("hr").get(1);
        String leader = leader("hr");
        String auditor = pack.employees().stream().filter(e -> e.grade().equals("ceo")).findFirst().orElseThrow().id();
        assertThat(reset()).isEqualTo(204);
        List<JsonNode> start = snapshot(emp, leader, auditor);
        assertThat(start.get(6).path("items").size()).isZero();

        // 쓰기 여러 가지: 상신·승인, 대결 등록, 회의실 예약, 되돌리기
        String day = LocalDate.now().plusDays(90).toString();
        JsonNode doc = json(post("/approval-documents", emp, Map.of("formId", "leave", "fields", Map.of(
                "leave_type", "annual", "start_date", day, "end_date", day, "reason", "평가"))));
        assertThat(post("/approval-documents/" + doc.path("resource").path("id").asText() + "/approve", leader,
                Map.of("version", doc.path("resource").path("version").asInt())).getStatus()).isEqualTo(201);
        OffsetDateTime now = OffsetDateTime.now(ZoneOffset.ofHours(9));
        assertThat(post("/delegations", leader, Map.of("delegateId", emp, "startsAt", now.toString(), "endsAt",
                now.plusDays(1).toString(), "scope", Map.of("formTypes", List.of("leave")), "reason", "출장"))
                .getStatus()).isEqualTo(201);
        OffsetDateTime s = LocalDate.now(ZoneOffset.ofHours(9)).plusDays(90).atTime(10, 0).atOffset(ZoneOffset.ofHours(9));
        JsonNode rsv = json(post("/room-reservations", emp, Map.of("roomId", "room-a", "startsAt", s.toString(),
                "endsAt", s.plusHours(1).toString(), "title", "평가")));
        assertThat(post("/actions/" + rsv.path("actionId").asText() + "/undo", emp, Map.of()).getStatus()).isEqualTo(201);
        assertThat(snapshot(emp, leader, auditor)).isNotEqualTo(start);

        assertThat(reset()).isEqualTo(204);
        assertThat(snapshot(emp, leader, auditor)).isEqualTo(start);
        // 되돌리기 기록도 비워져 옛 actionId는 없음
        assertThat(get("/actions/" + rsv.path("actionId").asText(), emp).getStatus()).isEqualTo(404);
        // 연차 잔여는 팩 고정 데이터 값
        var bal = pack.balances().stream().filter(b -> b.employeeId().equals(emp)).findFirst().orElseThrow();
        assertThat(start.get(0).path("annualUsed").asDouble()).isEqualTo(bal.annualUsed());
        assertThat(start.get(0).path("annualPending").asDouble()).isZero();
    }
}
