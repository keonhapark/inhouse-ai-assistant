package io.inhouse.erp.ticket;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.ApiTestBase;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletResponse;

/** IT 티켓: 팩 고정 데이터, 티켓 담당 역할, 상태 변경 되돌리기, 동시 상태 변경. 계약 행동 시험과 겹치지 않는 것만. */
class TicketApiTest extends ApiTestBase {

    private String handler() {
        return members("it-ops").get(0);
    }

    private JsonNode create(String emp) throws Exception {
        MockHttpServletResponse r = post("/tickets", emp, Map.of("category", "incident", "title", "메일 수신 지연",
                "description", "외부 메일이 30분 늦게 옵니다"));
        assertThat(r.getStatus()).as(r.getContentAsString()).isEqualTo(201);
        return json(r);
    }

    @Test
    void packFixtureTicketsAreSeededWithComments() throws Exception {
        JsonNode t = json(get("/tickets/tkt_0001", handler()));
        assertThat(t.path("requesterId").asText()).isEqualTo("E0023");
        assertThat(t.path("comments").findValuesAsText("id")).containsExactly("tcm_0001_1", "tcm_0001_2");
        assertThat(t.path("commentCount").asInt()).isEqualTo(2);
        // 마지막 댓글 시각이 updatedAt입니다(목록 정렬 기준)
        assertThat(t.path("updatedAt").asText()).isEqualTo(t.path("comments").get(1).path("createdAt").asText());
        assertThat(json(get("/tickets", "E0023")).path("items").findValuesAsText("id")).contains("tkt_0001");
    }

    @Test
    void handlerRoleComesFromPack() throws Exception {
        // 티켓 담당은 팩 erp_roles.ticket_handler(제조 팩 it_admin = IT운영팀)입니다.
        assertThat(get("/tickets", handler(), "box", "all").getStatus()).isEqualTo(200);
        assertThat(get("/tickets", leader("it-ops"), "box", "all").getStatus()).isEqualTo(200);
        assertThat(get("/tickets", members("hr").get(0), "box", "all").getStatus()).isEqualTo(403);
        assertThat(problem(get("/tickets", handler(), "box", "everyone"))).isEqualTo("validation");
        assertThat(problem(get("/tickets", handler(), "status", "done"))).isEqualTo("validation");
    }

    @Test
    void statusUndoRestoresPreviousStatusAndActionPointsToChange() throws Exception {
        String emp = members("procurement").get(0);
        String id = create(emp).path("resource").path("id").asText();
        JsonNode r = json(post("/tickets/" + id + "/status", handler(), Map.of("status", "resolved", "version", 0)));
        assertThat(r.path("resource").path("status").asText()).isEqualTo("resolved");
        JsonNode action = json(get("/actions/" + r.path("actionId").asText(), handler()));
        assertThat(action.path("resourceType").asText()).isEqualTo("ticket_status_change");
        assertThat(post("/actions/" + r.path("actionId").asText() + "/undo", handler(), Map.of()).getStatus())
                .isEqualTo(201);
        JsonNode t = json(get("/tickets/" + id, emp));
        assertThat(t.path("status").asText()).isEqualTo("open");
        assertThat(t.path("version").asInt()).isEqualTo(2);
    }

    @Test
    void concurrentStatusChangesOneWins() throws Exception {
        String id = create(members("procurement").get(1)).path("resource").path("id").asText();
        List<String> handlers = members("it-ops");
        ExecutorService pool = Executors.newFixedThreadPool(handlers.size());
        try {
            List<Callable<MockHttpServletResponse>> calls = handlers.stream()
                    .<Callable<MockHttpServletResponse>>map(h -> () -> post("/tickets/" + id + "/status", h,
                            Map.of("status", "in_progress", "version", 0)))
                    .toList();
            int ok = 0;
            for (Future<MockHttpServletResponse> f : pool.invokeAll(calls)) {
                MockHttpServletResponse r = f.get();
                if (r.getStatus() == 201) {
                    ok++;
                } else {
                    assertThat(r.getStatus()).isEqualTo(409);
                    assertThat(problem(r)).isEqualTo("version-conflict");
                }
            }
            assertThat(ok).isEqualTo(1);
        } finally {
            pool.shutdown();
        }
        assertThat(json(get("/tickets/" + id, handler())).path("version").asInt()).isEqualTo(1);
    }
}
