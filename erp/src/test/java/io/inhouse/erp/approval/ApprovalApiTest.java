package io.inhouse.erp.approval;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.ApiTestBase;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletResponse;

class ApprovalApiTest extends ApiTestBase {

    static final AtomicInteger DAY = new AtomicInteger(300);

    /** 시험마다 다른 미래 평일. */
    static String weekday() {
        LocalDate d;
        do {
            d = LocalDate.now().plusDays(DAY.incrementAndGet());
        } while (d.getDayOfWeek() == DayOfWeek.SATURDAY || d.getDayOfWeek() == DayOfWeek.SUNDAY);
        return d.toString();
    }

    private JsonNode leave(String emp, String type, String start, String end) throws Exception {
        MockHttpServletResponse r = post("/approval-documents", emp, Map.of("formId", "leave", "fields",
                Map.of("leave_type", type, "start_date", start, "end_date", end, "reason", "시험")));
        assertThat(r.getStatus()).as(r.getContentAsString()).isEqualTo(201);
        return json(r).path("resource");
    }

    private JsonNode expense(String emp, long amount) throws Exception {
        MockHttpServletResponse r = post("/approval-documents", emp, Map.of("formId", "expense", "fields",
                Map.of("amount", amount, "spent_on", "2026-11-02", "merchant", "가상상회", "purpose", "시험")));
        assertThat(r.getStatus()).as(r.getContentAsString()).isEqualTo(201);
        return json(r).path("resource");
    }

    private MockHttpServletResponse approve(String emp, JsonNode doc) throws Exception {
        return post("/approval-documents/" + doc.path("id").asText() + "/approve", emp,
                Map.of("version", doc.path("version").asInt()));
    }

    private JsonNode balance(String emp) throws Exception {
        return json(get("/leave/balance", emp));
    }

    private List<String> approvers(JsonNode doc) {
        List<String> out = new ArrayList<>();
        doc.path("steps").forEach(s -> out.add(s.path("approverId").asText()));
        return out;
    }

    @Test
    void approvalLineFollowsPackRules() throws Exception {
        String ceo = leader("ceo-office");
        // 팀원 → 팀장, 팀장 → 본부장, 본부장 → 대표이사, 대표이사 → 결재선 없음(바로 승인)
        assertThat(approvers(leave(members("quality").get(0), "special", weekday(), weekday())))
                .containsExactly(leader("quality"));
        assertThat(approvers(leave(leader("quality"), "special", weekday(), weekday())))
                .containsExactly(leader("production-div"));
        assertThat(approvers(leave(leader("production-div"), "special", weekday(), weekday()))).containsExactly(ceo);
        JsonNode own = leave(ceo, "special", weekday(), weekday());
        assertThat(approvers(own)).isEmpty();
        assertThat(own.path("status").asText()).isEqualTo("approved");
        // 본부 직속 팀(대표이사실 아래 팀)의 팀장 → 본부장이 없으니 대표이사
        assertThat(approvers(leave(leader("it-ops"), "special", weekday(), weekday()))).containsExactly(ceo);
        // 금액 기준: 100만 원 이하 팀장, 초과 팀장·본부장
        String member = members("sales").get(0);
        assertThat(approvers(expense(member, 1_000_000))).containsExactly(leader("sales"));
        assertThat(approvers(expense(member, 1_000_001))).containsExactly(leader("sales"), leader("sales-div"));
        // 팀장이 올린 큰 금액: 팀장 단계가 본부장으로 올라가 겹치므로 한 번만
        assertThat(approvers(expense(leader("sales"), 2_000_000))).containsExactly(leader("sales-div"));
    }

    @Test
    void formValidationReportsFields() throws Exception {
        String emp = members("quality").get(1);
        MockHttpServletResponse r = post("/approval-documents", emp, Map.of("formId", "leave", "fields",
                Map.of("leave_type", "vacation", "start_date", weekday(), "extra", 1)));
        assertThat(r.getStatus()).isEqualTo(422);
        assertThat(problem(r)).isEqualTo("form-validation-failed");
        List<String> fields = new ArrayList<>();
        json(r).path("errors").forEach(e -> fields.add(e.path("field").asText()));
        assertThat(fields).contains("leave_type", "end_date", "reason", "extra");

        r = post("/approval-documents", emp, Map.of("formId", "expense", "fields", Map.of("amount", 1000,
                "spent_on", "yesterday", "merchant", "가상상회", "purpose", "x")));
        assertThat(problem(r)).isEqualTo("form-validation-failed");
        assertThat(json(r).path("errors").get(0).path("field").asText()).isEqualTo("spent_on");
        r = post("/approval-documents", emp, Map.of("formId", "nope", "fields", Map.of()));
        assertThat(problem(r)).isEqualTo("validation");
        r = post("/approval-documents", emp, Map.of("formId", "leave"));
        assertThat(problem(r)).isEqualTo("validation");
        String day = weekday();
        r = post("/approval-documents", emp, Map.of("formId", "leave", "fields", Map.of("leave_type", "half_am",
                "start_date", day, "end_date", LocalDate.parse(day).plusDays(1).toString(), "reason", "x")));
        assertThat(problem(r)).isEqualTo("form-validation-failed");
        r = post("/approval-documents", emp, Map.of("formId", "leave", "fields", Map.of("leave_type", "annual",
                "start_date", "2026-13-01", "end_date", "2026-13-01", "reason", "x")));
        assertThat(problem(r)).isEqualTo("form-validation-failed");
    }

    @Test
    void leaveDaysCountWeekdaysAndHalfDays() {
        assertThat(io.inhouse.erp.leave.LeaveService.days("annual", "2026-11-20", "2026-11-24")).isEqualByComparingTo("3");
        assertThat(io.inhouse.erp.leave.LeaveService.days("half_pm", "2026-11-20", "2026-11-20")).isEqualByComparingTo("0.5");
        assertThat(io.inhouse.erp.leave.LeaveService.days("sick", "2026-11-20", "2026-11-27")).isEqualByComparingTo("0");
    }

    @Test
    void twoStepApprovalAdvancesAndNotifies() throws Exception {
        String emp = members("sales").get(1);
        JsonNode doc = expense(emp, 1_500_000);
        String first = leader("sales");
        String second = leader("sales-div");
        assertThat(json(get("/approval-documents", second, "box", "inbox")).path("items").findValuesAsText("id"))
                .doesNotContain(doc.path("id").asText());
        MockHttpServletResponse early = approve(second, doc);
        assertThat(early.getStatus()).isEqualTo(403);
        assertThat(problem(early)).isEqualTo("not-current-approver");

        JsonNode afterFirst = json(approve(first, doc)).path("resource");
        assertThat(afterFirst.path("currentStep").asInt()).isEqualTo(2);
        assertThat(afterFirst.path("version").asInt()).isGreaterThan(doc.path("version").asInt());
        assertThat(json(get("/approval-documents", second, "box", "inbox")).path("items").findValuesAsText("id"))
                .contains(doc.path("id").asText());
        assertThat(json(get("/notifications", second)).path("items").findValuesAsText("kind")).contains("approval_turn");
        // 화면이 본 옛 version으로 결재하면 409
        MockHttpServletResponse stale = approve(second, doc);
        assertThat(problem(stale)).isEqualTo("version-conflict");
        JsonNode done = json(approve(second, afterFirst)).path("resource");
        assertThat(done.path("status").asText()).isEqualTo("approved");
        assertThat(done.path("currentStep").isNull()).isTrue();
        assertThat(json(get("/approval-documents", first, "box", "done")).path("items").findValuesAsText("id"))
                .contains(doc.path("id").asText());
        assertThat(json(get("/notifications", emp, "unreadOnly", "true")).path("items").findValuesAsText("message"))
                .anyMatch(m -> m.startsWith("승인 완료"));
        // 끝난 문서는 다시 결재할 수 없음
        assertThat(problem(approve(second, done))).isEqualTo("invalid-state");
    }

    @Test
    void concurrentApprovalsOnlyOneWins() throws Exception {
        String emp = members("quality").get(2);
        String day = weekday();
        JsonNode doc = leave(emp, "half_am", day, day);
        String approver = leader("quality");
        int n = 4;
        ExecutorService pool = Executors.newFixedThreadPool(n);
        CountDownLatch go = new CountDownLatch(1);
        List<Future<MockHttpServletResponse>> futures = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            Callable<MockHttpServletResponse> c = () -> {
                go.await();
                return approve(approver, doc);
            };
            futures.add(pool.submit(c));
        }
        go.countDown();
        List<String> outcomes = new ArrayList<>();
        for (Future<MockHttpServletResponse> f : futures) {
            MockHttpServletResponse r = f.get();
            outcomes.add(r.getStatus() == 201 ? "ok" : problem(r));
        }
        pool.shutdown();
        assertThat(outcomes).containsOnlyOnce("ok");
        assertThat(outcomes).filteredOn(o -> !o.equals("ok")).allMatch(o -> o.equals("version-conflict")
                || o.equals("invalid-state"));
    }

    @Test
    void leaveBalanceMovesWithDocument() throws Exception {
        String emp = members("production-control").get(0);
        JsonNode bal0 = balance(emp);
        String day = weekday();
        JsonNode doc = leave(emp, "annual", day, day);
        assertThat(balance(emp).path("annualPending").decimalValue())
                .isEqualByComparingTo(bal0.path("annualPending").decimalValue().add(java.math.BigDecimal.ONE));
        // 반려: pending 원래대로
        MockHttpServletResponse r = post("/approval-documents/" + doc.path("id").asText() + "/reject",
                leader("production-control"), Map.of("version", doc.path("version").asInt(), "comment", "일정"));
        assertThat(r.getStatus()).isEqualTo(201);
        assertThat(json(r).path("resource").path("steps").get(0).path("comment").asText()).isEqualTo("일정");
        assertThat(balance(emp)).isEqualTo(bal0);
        // 승인 뒤 시작 전 회수: used 원래대로
        JsonNode doc2 = leave(emp, "annual", day, day);
        assertThat(approve(leader("production-control"), doc2).getStatus()).isEqualTo(201);
        assertThat(balance(emp).path("annualUsed").decimalValue())
                .isEqualByComparingTo(bal0.path("annualUsed").decimalValue().add(java.math.BigDecimal.ONE));
        r = post("/approval-documents/" + doc2.path("id").asText() + "/withdraw", emp, Map.of());
        assertThat(r.getStatus()).isEqualTo(201);
        assertThat(balance(emp)).isEqualTo(bal0);
        assertThat(problem(post("/approval-documents/" + doc2.path("id").asText() + "/withdraw", emp, Map.of())))
                .isEqualTo("invalid-state");
    }

    @Test
    void undoCreateWithdrawsUntilSomeoneActs() throws Exception {
        String emp = members("production-control").get(1);
        String day = weekday();
        MockHttpServletResponse created = post("/approval-documents", emp, Map.of("formId", "leave", "fields",
                Map.of("leave_type", "half_pm", "start_date", day, "end_date", day, "reason", "시험")));
        JsonNode res = json(created);
        MockHttpServletResponse undo = post("/actions/" + res.path("actionId").asText() + "/undo", emp, Map.of());
        assertThat(undo.getStatus()).isEqualTo(201);
        assertThat(json(undo).path("resource").path("status").asText()).isEqualTo("withdrawn");

        JsonNode res2 = json(post("/approval-documents", emp, Map.of("formId", "leave", "fields",
                Map.of("leave_type", "half_pm", "start_date", day, "end_date", day, "reason", "시험"))));
        assertThat(approve(leader("production-control"), res2.path("resource")).getStatus()).isEqualTo(201);
        MockHttpServletResponse conflict = post("/actions/" + res2.path("actionId").asText() + "/undo", emp, Map.of());
        assertThat(problem(conflict)).isEqualTo("undo-conflict");
    }

    @Test
    void visibilityAndSelfApproval() throws Exception {
        String emp = members("production-control").get(2);
        String day = weekday();
        JsonNode doc = leave(emp, "half_am", day, day);
        String id = doc.path("id").asText();
        assertThat(get("/approval-documents/" + id, members("quality").get(0)).getStatus()).isEqualTo(404);
        assertThat(get("/approval-documents/" + id, leader("production-control")).getStatus()).isEqualTo(200);
        assertThat(approve(members("quality").get(0), doc).getStatus()).isEqualTo(404);
        assertThat(problem(approve(emp, doc))).isEqualTo("self-approval-forbidden");
        assertThat(problem(post("/approval-documents/" + id + "/withdraw", members("production-control").get(3),
                Map.of()))).isIn("not-found", "forbidden");
        assertThat(problem(post("/approval-documents/" + id + "/approve", leader("production-control"),
                Map.of("comment", "x")))).isEqualTo("validation");
        assertThat(get("/approval-documents", emp, "box", "nope").getStatus()).isEqualTo(422);
        assertThat(json(get("/approval-documents", emp, "box", "outbox", "status", "in_progress")).path("items")
                .findValuesAsText("id")).contains(id);
        assertThat(json(get("/approval-documents", emp, "box", "outbox", "status", "approved")).path("items")
                .findValuesAsText("id")).doesNotContain(id);
        assertThat(json(get("/approval-documents", emp, "box", "outbox", "limit", "1")).path("items").size())
                .isEqualTo(1);
        assertThat(json(get("/approval-documents", leader("production-control"), "box", "inbox", "status",
                "in_progress")).path("items").findValuesAsText("id")).contains(id);
    }

    @Test
    void otherBalanceOnlyForHr() throws Exception {
        String emp = members("sales").get(2);
        assertThat(get("/leave/balance", members("quality").get(0), "employeeId", emp).getStatus()).isEqualTo(403);
        assertThat(get("/leave/balance", members("hr").get(0), "employeeId", emp).getStatus()).isEqualTo(200);
    }
}
