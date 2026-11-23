package io.inhouse.erp.delegation;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.ApiTestBase;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
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

class DelegationApiTest extends ApiTestBase {

    static final AtomicInteger DAY = new AtomicInteger(500);
    static final ZoneOffset KST = ZoneOffset.ofHours(9);

    static String weekday() {
        LocalDate d;
        do {
            d = LocalDate.now().plusDays(DAY.incrementAndGet());
        } while (d.getDayOfWeek() == DayOfWeek.SATURDAY || d.getDayOfWeek() == DayOfWeek.SUNDAY);
        return d.toString();
    }

    private Map<String, Object> body(String delegate, OffsetDateTime start, double days, List<String> forms,
                                     Long maxAmount) {
        Map<String, Object> scope = new HashMap<>();
        scope.put("formTypes", forms);
        scope.put("maxAmount", maxAmount);
        return new HashMap<>(Map.of("delegateId", delegate, "startsAt", start.toString(),
                "endsAt", start.plusMinutes((long) (days * 24 * 60)).toString(), "scope", scope, "reason", "출장"));
    }

    private MockHttpServletResponse register(String as, Map<String, Object> body) throws Exception {
        return post("/delegations", as, body);
    }

    private JsonNode delegate(String from, String to, List<String> forms, Long max) throws Exception {
        MockHttpServletResponse r = register(from, body(to, OffsetDateTime.now(KST).minusMinutes(1), 3, forms, max));
        assertThat(r.getStatus()).as(r.getContentAsString()).isEqualTo(201);
        return json(r);
    }

    private JsonNode leave(String emp) throws Exception {
        String day = weekday();
        MockHttpServletResponse r = post("/approval-documents", emp, Map.of("formId", "leave", "fields",
                Map.of("leave_type", "half_am", "start_date", day, "end_date", day, "reason", "시험")));
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

    @Test
    void delegateApprovesWithinPeriodAndScope() throws Exception {
        String leader = leader("quality");
        String delegate = members("quality").get(3);
        String requester = members("quality").get(4);
        JsonNode dl = delegate(leader, delegate, List.of("leave"), null).path("resource");
        assertThat(dl.path("status").asText()).isEqualTo("active");
        assertThat(dl.path("startsAt").asText()).endsWith("+09:00");
        assertThat(json(get("/notifications", delegate)).path("items").findValuesAsText("kind"))
                .contains("delegation_registered");

        JsonNode doc = leave(requester);
        String id = doc.path("id").asText();
        assertThat(get("/approval-documents/" + id, delegate).getStatus()).isEqualTo(200);
        assertThat(json(get("/approval-documents", delegate, "box", "delegated")).path("items").findValuesAsText("id"))
                .contains(id);
        MockHttpServletResponse r = approve(delegate, doc);
        assertThat(r.getStatus()).as(r.getContentAsString()).isEqualTo(201);
        JsonNode step = json(r).path("resource").path("steps").get(0);
        assertThat(step.path("approverId").asText()).isEqualTo(leader);
        assertThat(step.path("actedBy").asText()).isEqualTo(delegate);
        assertThat(step.path("onBehalfOf").asText()).isEqualTo(leader);
        assertThat(step.path("delegationId").asText()).isEqualTo(dl.path("id").asText());
        assertThat(json(r).path("summary").asText()).contains("대결");
        // 후열 알림, 대결 결재 문서, 처리한 결재함
        JsonNode notes = json(get("/notifications", leader)).path("items");
        assertThat(notes.findValuesAsText("kind")).contains("delegated_decision");
        assertThat(json(get("/delegations/" + dl.path("id").asText() + "/acted-documents", leader)).path("items")
                .findValuesAsText("id")).contains(id);
        assertThat(json(get("/approval-documents", delegate, "box", "done")).path("items").findValuesAsText("id"))
                .contains(id);
        // 감사 이벤트에 원 결재자·위임 ID
        String auditor = pack.employees().stream().filter(e -> e.grade().equals("ceo")).findFirst().orElseThrow().id();
        JsonNode events = json(get("/audit-events", auditor, "actionId", json(r).path("actionId").asText()))
                .path("items");
        assertThat(events.get(0).path("onBehalfOf").asText()).isEqualTo(leader);
        assertThat(events.get(0).path("delegationId").asText()).isEqualTo(dl.path("id").asText());
    }

    @Test
    void rejectsOutsidePeriodScopeOrAfterRevoke() throws Exception {
        String leader = leader("procurement");
        List<String> m = members("procurement");
        String requester = m.get(0);
        // 기간 전(예약)
        MockHttpServletResponse r = register(leader, body(m.get(1), OffsetDateTime.now(KST).plusDays(2), 2,
                List.of("*"), null));
        assertThat(json(r).path("resource").path("status").asText()).isEqualTo("scheduled");
        assertThat(problem(approve(m.get(1), leave(requester)))).isEqualTo("delegation-out-of-period");
        // 양식 범위 밖, 금액 한도: 넘으면 거절, 이하면 승인
        delegate(leader, m.get(2), List.of("expense"), 100_000L);
        assertThat(problem(approve(m.get(2), leave(requester)))).isEqualTo("delegation-out-of-scope");
        assertThat(problem(approve(m.get(2), expense(requester, 500_000)))).isEqualTo("delegation-out-of-scope");
        assertThat(approve(m.get(2), expense(requester, 50_000)).getStatus()).isEqualTo(201);
        // 금액이 없는 양식에는 한도를 쓰지 않음
        String revokeId = delegate(leader, m.get(3), List.of("leave"), 1L).path("resource").path("id").asText();
        assertThat(approve(m.get(3), leave(requester)).getStatus()).isEqualTo(201);
        // 해지 뒤
        assertThat(post("/delegations/" + revokeId + "/revoke", leader, Map.of()).getStatus()).isEqualTo(201);
        assertThat(problem(approve(m.get(3), leave(requester)))).isEqualTo("delegation-revoked");
        assertThat(problem(post("/delegations/" + revokeId + "/revoke", leader, Map.of()))).isEqualTo("invalid-state");
    }

    @Test
    void noRedelegationNoSelfApproval() throws Exception {
        String leader = leader("rnd");
        List<String> m = members("rnd");
        delegate(leader, m.get(2), List.of("*"), null);
        delegate(m.get(2), m.get(3), List.of("*"), null);
        assertThat(problem(approve(m.get(3), leave(m.get(4))))).isEqualTo("redelegation-not-allowed");
        // 대리인이 올린 자기 문서
        JsonNode own = leave(m.get(2));
        assertThat(problem(approve(m.get(2), own))).isEqualTo("self-approval-forbidden");
    }

    @Test
    void approverAndDelegateAtOnceOnlyOneWins() throws Exception {
        String leader = leader("general-affairs");
        List<String> m = members("general-affairs");
        delegate(leader, m.get(0), List.of("*"), null);
        JsonNode doc = leave(m.get(1));
        ExecutorService pool = Executors.newFixedThreadPool(2);
        CountDownLatch go = new CountDownLatch(1);
        List<Future<MockHttpServletResponse>> fs = new ArrayList<>();
        for (String who : List.of(leader, m.get(0))) {
            Callable<MockHttpServletResponse> c = () -> {
                go.await();
                return approve(who, doc);
            };
            fs.add(pool.submit(c));
        }
        go.countDown();
        List<Integer> codes = new ArrayList<>();
        for (Future<MockHttpServletResponse> f : fs) {
            codes.add(f.get().getStatus());
        }
        pool.shutdown();
        assertThat(codes).containsExactlyInAnyOrder(201, 409);
    }

    @Test
    void registrationRules() throws Exception {
        String leader = leader("sales");
        List<String> m = members("sales");
        String hr = members("hr").get(0);
        OffsetDateTime now = OffsetDateTime.now(KST);

        Map<String, Object> forOther = body(m.get(0), now, 1, List.of("leave"), null);
        forOther.put("delegatorId", leader);
        assertThat(problem(register(m.get(1), forOther))).isEqualTo("delegation-registrar-forbidden");
        assertThat(problem(register(leader, body(leader, now, 1, List.of("leave"), null)))).isEqualTo("delegation-self");
        assertThat(problem(register(leader, body(m.get(0), now, 31, List.of("leave"), null))))
                .isEqualTo("delegation-period-too-long");
        assertThat(problem(register(leader, body(m.get(0), now, 1, List.of("no-such-form"), null))))
                .isEqualTo("validation");
        assertThat(problem(register(leader, body(m.get(0), now.minusDays(3), 1, List.of("leave"), null))))
                .isEqualTo("validation");
        assertThat(problem(register(leader, body(m.get(0), now, 0, List.of("leave"), null)))).isEqualTo("validation");
        Map<String, Object> noOffset = body(m.get(0), now, 1, List.of("leave"), null);
        noOffset.put("startsAt", "2026-12-01T09:00:00");
        assertThat(problem(register(leader, noOffset))).isEqualTo("validation");
        Map<String, Object> extra = body(m.get(0), now, 1, List.of("leave"), null);
        extra.put("note", "x");
        assertThat(problem(register(leader, extra))).isEqualTo("validation");
        // 30일 정확히는 허용
        assertThat(register(leader, body(m.get(2), now, 30, List.of("leave"), null)).getStatus()).isEqualTo(201);

        // 인사 담당은 다른 사람 대신 등록
        MockHttpServletResponse r = register(hr, forOther);
        assertThat(r.getStatus()).isEqualTo(201);
        JsonNode dl = json(r).path("resource");
        assertThat(dl.path("delegatorId").asText()).isEqualTo(leader);
        assertThat(dl.path("registeredBy").asText()).isEqualTo(hr);
        assertThat(json(get("/notifications", leader)).path("items").findValuesAsText("message"))
                .anyMatch(msg -> msg.contains("내 대결자로 지정"));
        assertThat(json(get("/delegations", leader, "role", "delegator")).path("items").findValuesAsText("id"))
                .contains(dl.path("id").asText());
        assertThat(json(get("/delegations", m.get(0), "role", "delegate", "activeAt",
                now.plusHours(1).toString())).path("items").findValuesAsText("id")).contains(dl.path("id").asText());
        assertThat(json(get("/delegations", m.get(0), "role", "delegate", "activeAt",
                now.plusDays(5).toString())).path("items").findValuesAsText("id")).doesNotContain(dl.path("id").asText());
        assertThat(get("/delegations", m.get(0), "role", "all").getStatus()).isEqualTo(403);
        assertThat(get("/delegations", hr, "role", "all").getStatus()).isEqualTo(200);
        assertThat(get("/delegations/" + dl.path("id").asText(), m.get(3)).getStatus()).isEqualTo(404);
        // 대리인은 해지하지 못함(볼 수는 있음)
        assertThat(problem(post("/delegations/" + dl.path("id").asText() + "/revoke", m.get(0), Map.of())))
                .isEqualTo("forbidden");
        // 등록 되돌리기 = 해지
        MockHttpServletResponse undo = post("/actions/" + json(r).path("actionId").asText() + "/undo", hr, Map.of());
        assertThat(undo.getStatus()).isEqualTo(201);
        assertThat(json(get("/delegations/" + dl.path("id").asText(), leader)).path("status").asText())
                .isEqualTo("revoked");
    }

    @Test
    void usedDelegationCannotBeUndone() throws Exception {
        String leader = leader("finance");
        List<String> m = members("finance");
        JsonNode reg = delegate(leader, m.get(0), List.of("*"), null);
        assertThat(approve(m.get(0), leave(m.get(1))).getStatus()).isEqualTo(201);
        MockHttpServletResponse undo = post("/actions/" + reg.path("actionId").asText() + "/undo", leader, Map.of());
        assertThat(problem(undo)).isEqualTo("undo-conflict");
        assertThat(post("/delegations/" + reg.path("resource").path("id").asText() + "/revoke", leader, Map.of())
                .getStatus()).isEqualTo(201);
    }

    @org.springframework.beans.factory.annotation.Autowired DelegationAuthority authority;
    @org.springframework.beans.factory.annotation.Autowired DelegationRepository delegationRepo;
    @org.springframework.beans.factory.annotation.Autowired io.inhouse.erp.approval.ApprovalDocumentRepository docRepo;
    @org.springframework.beans.factory.annotation.Autowired
    org.springframework.transaction.support.TransactionTemplate tx;

    /** 결재 트랜잭션이 위임을 먼저 읽은 뒤 다른 요청이 해지를 커밋해도, 판단은 해지된 값으로 합니다. */
    @Test
    void revokeCommittedMidDecisionIsSeen() throws Exception {
        String leader = leader("rnd");
        List<String> m = members("rnd");
        String dlId = delegate(leader, m.get(5), List.of("*"), null).path("resource").path("id").asText();
        String docId = leave(m.get(6)).path("id").asText();
        String code = tx.execute(status -> {
            delegationRepo.findByDelegatorIdAndDelegateId(leader, m.get(5));  // 영속성 문맥에 먼저 올림
            Thread revoker = new Thread(() -> {
                try {
                    assertThat(post("/delegations/" + dlId + "/revoke", leader, Map.of()).getStatus()).isEqualTo(201);
                } catch (Exception e) {
                    throw new IllegalStateException(e);
                }
            });
            revoker.start();
            try {
                revoker.join();
                authority.authorize(docRepo.findById(docId).orElseThrow(), leader, m.get(5));
                return "authorized";
            } catch (io.inhouse.erp.common.ApiException e) {
                return e.code();
            } catch (InterruptedException e) {
                throw new IllegalStateException(e);
            } finally {
                status.setRollbackOnly();
            }
        });
        assertThat(code).isEqualTo("delegation-revoked");
    }
}
