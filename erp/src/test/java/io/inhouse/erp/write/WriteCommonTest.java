package io.inhouse.erp.write;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.inhouse.erp.PostgresTestBase;
import io.inhouse.erp.auth.Tokens;
import io.inhouse.erp.leave.LeaveBalance;
import io.inhouse.erp.leave.LeaveBalanceRepository;
import io.inhouse.erp.pack.Pack;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;

@AutoConfigureMockMvc
class WriteCommonTest extends PostgresTestBase {

    /** 계약 audit.schema.json의 필드 이름. erp가 다른 필드를 넣지 않는지 봅니다. */
    static final Set<String> AUDIT_FIELDS = Set.of("eventId", "occurredAt", "source", "kind", "actor", "onBehalfOf",
            "delegationId", "conversationId", "executionApprovalId", "actionId", "undoOf", "operation", "argsHash",
            "riskLevel", "trustLevel", "routing", "model", "result", "problemType", "detail");
    static final Set<String> ACTOR_FIELDS = Set.of("employeeId", "viaDelegationToken", "channel", "delegationTokenId",
            "agentId");
    static final AtomicInteger NEXT = new AtomicInteger(20);

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;
    @Autowired Pack pack;
    @Autowired LeaveBalanceRepository balances;
    @Autowired JdbcTemplate jdbc;

    /** 시험마다 다른 직원(연차 잔여가 있는). */
    private String someone() {
        return pack.balances().get(NEXT.getAndIncrement()).employeeId();
    }

    private String jwt(String emp) {
        return Tokens.hs256(new com.nimbusds.jwt.JWTClaimsSet.Builder().issuer("erp").audience("erp").subject(emp)
                .expirationTime(new java.util.Date(System.currentTimeMillis() + 600_000)).build(), JWT_SECRET);
    }

    private MockHttpServletRequestBuilder write(String path, String emp, String key, Object body) throws Exception {
        MockHttpServletRequestBuilder b = post(path).header("Authorization", "Bearer " + jwt(emp))
                .contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(body));
        return key == null ? b : b.header("Idempotency-Key", key);
    }

    private JsonNode json(MockHttpServletResponse r) throws Exception {
        return mapper.readTree(r.getContentAsString());
    }

    private BigDecimal pending(String emp) {
        return balances.findById(new LeaveBalance.Key(emp, WriteProbeController.YEAR)).orElseThrow().getAnnualPending();
    }

    private static String key() {
        return UUID.randomUUID().toString();
    }

    private JsonNode add(String emp, String path) throws Exception {
        return json(mvc.perform(write(path, emp, key(), java.util.Map.of("days", 1)))
                .andExpect(status().isCreated()).andReturn().getResponse());
    }

    @Test
    void dryRunPreviewsWithoutChangingState() throws Exception {
        String emp = someone();
        BigDecimal before = pending(emp);
        mvc.perform(write(WriteProbeController.PATH + "?dryRun=true", emp, null, java.util.Map.of("days", 1)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.dryRun").value(true))
                .andExpect(jsonPath("$.operation").value("probeAddPending"))
                .andExpect(jsonPath("$.undoable").value(true))
                .andExpect(jsonPath("$.warnings").isArray())
                .andExpect(jsonPath("$.changes[0].resourceId").value(emp))
                .andExpect(jsonPath("$.changes[1].op").value("create"))
                .andExpect(jsonPath("$.changes[1].resourceId").value(org.hamcrest.Matchers.nullValue()))
                .andExpect(jsonPath("$.actionId").doesNotExist());
        assertThat(pending(emp)).isEqualByComparingTo(before);
    }

    @Test
    void dryRunReportsSameValidationErrors() throws Exception {
        String emp = someone();
        for (String suffix : List.of("?dryRun=true", "")) {
            mvc.perform(write(WriteProbeController.PATH + suffix, emp, key(), java.util.Map.of("days", 0)))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.type").value("urn:problem:validation"))
                    .andExpect(jsonPath("$.errors[0].field").value("days"));
        }
    }

    @Test
    void executionNeedsIdempotencyKeyOf8To128() throws Exception {
        String emp = someone();
        for (String bad : new String[] {null, "short", "x".repeat(129)}) {
            mvc.perform(write(WriteProbeController.PATH, emp, bad, java.util.Map.of("days", 1)))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.type").value("urn:problem:idempotency-key-required"));
        }
        assertThat(pending(emp)).isEqualByComparingTo(BigDecimal.ZERO);
    }

    @Test
    void sameKeySameBodyReplaysFirstResponse() throws Exception {
        String emp = someone();
        String k = key();
        JsonNode first = json(mvc.perform(write(WriteProbeController.PATH, emp, k,
                mapper.readTree("{\"days\": 1, \"note\": {\"a\": 1, \"b\": 2}}"))).andExpect(status().isCreated())
                .andReturn().getResponse());
        // 키 순서만 다른 같은 본문
        JsonNode second = json(mvc.perform(write(WriteProbeController.PATH, emp, k,
                mapper.readTree("{\"note\": {\"b\": 2, \"a\": 1}, \"days\": 1}"))).andExpect(status().isCreated())
                .andReturn().getResponse());
        assertThat(second).isEqualTo(first);
        assertThat(pending(emp)).isEqualByComparingTo("1");
        // 같은 키라도 다른 사람이면 따로입니다
        String other = someone();
        mvc.perform(write(WriteProbeController.PATH, other, k, mapper.readTree("{\"days\": 1}")))
                .andExpect(status().isCreated());
        assertThat(pending(other)).isEqualByComparingTo("1");
    }

    @Test
    void sameKeyDifferentBodyIs422() throws Exception {
        String emp = someone();
        String k = key();
        mvc.perform(write(WriteProbeController.PATH, emp, k, java.util.Map.of("days", 1))).andExpect(status().isCreated());
        mvc.perform(write(WriteProbeController.PATH, emp, k, java.util.Map.of("days", 2)))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.type").value("urn:problem:idempotency-key-reused"));
        assertThat(pending(emp)).isEqualByComparingTo("1");
        Integer denied = jdbc.queryForObject("select count(*) from audit_event where actor_id = ? and kind = 'erp.denied'"
                + " and event->>'problemType' = 'urn:problem:idempotency-key-reused'", Integer.class, emp);
        assertThat(denied).isEqualTo(1);
    }

    @Test
    void keyExpiresAfter24Hours() throws Exception {
        String emp = someone();
        String k = key();
        String first = add(emp, WriteProbeController.PATH).path("actionId").asText();
        jdbc.update("update idempotency_record set created_at = now() - interval '25 hours' where owner_id = ?", emp);
        String again = json(mvc.perform(write(WriteProbeController.PATH, emp, k, java.util.Map.of("days", 1)))
                .andExpect(status().isCreated()).andReturn().getResponse()).path("actionId").asText();
        assertThat(again).isNotEqualTo(first);
    }

    /** 같은 요청 n개를 동시에 보내고, 모두 201이며 actionId가 하나인지 봅니다. */
    private Set<String> concurrently(int n, String path, String emp, String k, Object body) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(n);
        CountDownLatch go = new CountDownLatch(1);
        List<Future<MockHttpServletResponse>> futures = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            Callable<MockHttpServletResponse> c = () -> {
                go.await();
                return mvc.perform(write(path, emp, k, body)).andReturn().getResponse();
            };
            futures.add(pool.submit(c));
        }
        go.countDown();
        Set<String> ids = new java.util.HashSet<>();
        for (Future<MockHttpServletResponse> f : futures) {
            MockHttpServletResponse r = f.get();
            assertThat(r.getStatus()).as(r.getContentAsString()).isEqualTo(201);
            ids.add(json(r).path("actionId").asText());
        }
        pool.shutdown();
        return ids;
    }

    @Test
    void concurrentSameKeyRunsOnce() throws Exception {
        String emp = someone();
        assertThat(concurrently(6, WriteProbeController.PATH, emp, key(), java.util.Map.of("days", 1))).hasSize(1);
        assertThat(pending(emp)).isEqualByComparingTo("1");
    }

    @Test
    void concurrentSameKeyUndoReplaysInsteadOf409() throws Exception {
        String emp = someone();
        String actionId = add(emp, WriteProbeController.PATH).path("actionId").asText();
        assertThat(concurrently(4, "/actions/" + actionId + "/undo", emp, key(), java.util.Map.of())).hasSize(1);
        assertThat(pending(emp)).isEqualByComparingTo("0");
    }

    @Test
    void concurrentReuseOfExpiredKeyRunsOnce() throws Exception {
        String emp = someone();
        String k = key();
        mvc.perform(write(WriteProbeController.PATH, emp, k, java.util.Map.of("days", 1))).andExpect(status().isCreated());
        jdbc.update("update idempotency_record set created_at = now() - interval '25 hours' where owner_id = ?", emp);
        assertThat(concurrently(4, WriteProbeController.PATH, emp, k, java.util.Map.of("days", 1))).hasSize(1);
        assertThat(pending(emp)).isEqualByComparingTo("2");
    }

    @Test
    void undoPreviewThenUndoThenAlreadyUndone() throws Exception {
        String emp = someone();
        String actionId = add(emp, WriteProbeController.PATH).path("actionId").asText();
        String undoPath = "/actions/" + actionId + "/undo";
        mvc.perform(write(undoPath + "?dryRun=true", emp, null, java.util.Map.of()))
                .andExpect(status().isOk()).andExpect(jsonPath("$.dryRun").value(true));
        assertThat(pending(emp)).isEqualByComparingTo("1");
        mvc.perform(write(undoPath, emp, key(), java.util.Map.of()))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.undoOf").value(actionId))
                .andExpect(jsonPath("$.operation").value("undoAction"))
                .andExpect(jsonPath("$.undoable").value(false));
        assertThat(pending(emp)).isEqualByComparingTo("0");
        mvc.perform(get("/actions/" + actionId).header("Authorization", "Bearer " + jwt(emp)))
                .andExpect(jsonPath("$.status").value("undone"))
                .andExpect(jsonPath("$.undoActionId").isString())
                .andExpect(jsonPath("$.viaDelegationToken").value(false));
        mvc.perform(write(undoPath, emp, key(), java.util.Map.of()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.type").value("urn:problem:already-undone"));
    }

    @Test
    void undoConflictsWhenStateChanged() throws Exception {
        String emp = someone();
        String actionId = add(emp, WriteProbeController.PATH).path("actionId").asText();
        jdbc.update("update leave_balance set annual_pending = 0 where employee_id = ?", emp);
        mvc.perform(write("/actions/" + actionId + "/undo", emp, key(), java.util.Map.of()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.type").value("urn:problem:undo-conflict"));
        mvc.perform(get("/actions/" + actionId).header("Authorization", "Bearer " + jwt(emp)))
                .andExpect(jsonPath("$.status").value("done"));
    }

    @Test
    void irreversibleIsNotUndoable() throws Exception {
        String emp = someone();
        JsonNode res = add(emp, WriteProbeController.IRREVERSIBLE_PATH);
        assertThat(res.path("undoable").asBoolean()).isFalse();
        mvc.perform(write("/actions/" + res.path("actionId").asText() + "/undo", emp, key(), java.util.Map.of()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.type").value("urn:problem:not-undoable"));
    }

    @Test
    void othersActionIsNotFound() throws Exception {
        String emp = someone();
        String actionId = add(emp, WriteProbeController.PATH).path("actionId").asText();
        String other = someone();
        mvc.perform(write("/actions/" + actionId + "/undo", other, key(), java.util.Map.of()))
                .andExpect(status().isNotFound());
        mvc.perform(get("/actions/" + actionId).header("Authorization", "Bearer " + jwt(other)))
                .andExpect(status().isNotFound());
    }

    @Test
    void delegationTokenActionBelongsToTokenOwner() throws Exception {
        String emp = someone();
        String tok = Tokens.delegation(emp, List.of("leave:read", "action:read", "action:undo"));
        JsonNode res = json(mvc.perform(post(WriteProbeController.PATH).header("Authorization", "Bearer " + tok)
                        .header("Idempotency-Key", key()).contentType(MediaType.APPLICATION_JSON).content("{\"days\":1}"))
                .andExpect(status().isCreated()).andReturn().getResponse());
        String id = res.path("actionId").asText();
        mvc.perform(get("/actions/" + id).header("Authorization", "Bearer " + jwt(emp)))
                .andExpect(jsonPath("$.actorId").value(emp))
                .andExpect(jsonPath("$.viaDelegationToken").value(true))
                .andExpect(jsonPath("$.agentId").value("hr"))
                .andExpect(jsonPath("$.conversationId").value("cnv_test"));
        mvc.perform(post("/actions/" + id + "/undo").header("Authorization", "Bearer " + tok)
                .header("Idempotency-Key", key())).andExpect(status().isCreated());

        // 감사 이벤트에 위임 토큰 ID(jti)가 남아 gateway의 토큰 발급 이벤트와 이어집니다.
        String jti = com.nimbusds.jwt.SignedJWT.parse(tok).getJWTClaimsSet().getJWTID();
        List<String> kinds = jdbc.queryForList("select kind from audit_event where actor_id = ?"
                + " and event->'actor'->>'delegationTokenId' = ? and event->'actor'->>'channel' = 'agent' order by seq",
                String.class, emp, jti);
        assertThat(kinds).containsExactly("erp.write", "erp.undo");
    }

    @Test
    void auditEventsForAuditorOnly() throws Exception {
        String emp = someone();
        String actionId = add(emp, WriteProbeController.PATH).path("actionId").asText();
        mvc.perform(write("/actions/" + actionId + "/undo", emp, key(), java.util.Map.of())).andExpect(status().isCreated());
        mvc.perform(write(WriteProbeController.PATH, emp, key(), java.util.Map.of("days", -1)))
                .andExpect(status().isUnprocessableEntity());

        String auditor = pack.employees().stream().filter(e -> e.grade().equals("ceo")).findFirst().orElseThrow().id();
        mvc.perform(get("/audit-events").header("Authorization", "Bearer " + jwt(emp)))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.type").value("urn:problem:forbidden"));
        mvc.perform(get("/audit-events").header("Authorization", "Bearer " + Tokens.delegation(auditor,
                        List.of("audit:read"))))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.type").value("urn:problem:delegation-token-not-allowed"));

        JsonNode items = json(mvc.perform(get("/audit-events").param("actorId", emp).param("limit", "500")
                .header("Authorization", "Bearer " + jwt(auditor))).andExpect(status().isOk())
                .andReturn().getResponse()).path("items");
        List<String> kinds = new ArrayList<>();
        for (JsonNode ev : items) {
            ev.fieldNames().forEachRemaining(f -> assertThat(AUDIT_FIELDS).contains(f));
            assertThat(ev.path("source").asText()).isEqualTo("erp");
            assertThat(ev.path("actor").path("employeeId").asText()).isEqualTo(emp);
            assertThat(ev.path("actor").path("delegationTokenId").isNull()).isTrue();
            ev.path("actor").fieldNames().forEachRemaining(f -> assertThat(ACTOR_FIELDS).contains(f));
            assertThat(ev.path("actor").path("channel").asText()).isEqualTo("web");
            kinds.add(ev.path("kind").asText() + "/" + ev.path("result").asText());
        }
        assertThat(kinds).containsSubsequence("erp.write/ok", "erp.undo/ok", "erp.denied/denied");
        JsonNode undo = items.get(kinds.indexOf("erp.undo/ok"));
        assertThat(undo.path("undoOf").asText()).isEqualTo(actionId);
        JsonNode denied = items.get(kinds.indexOf("erp.denied/denied"));
        assertThat(denied.path("problemType").asText()).isEqualTo("urn:problem:validation");

        mvc.perform(get("/audit-events").param("actionId", actionId).header("Authorization", "Bearer " + jwt(auditor)))
                .andExpect(jsonPath("$.items.length()").value(1))
                .andExpect(jsonPath("$.items[0].kind").value("erp.write"));
    }
}
