package io.inhouse.erp.room;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.ApiTestBase;
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

class RoomApiTest extends ApiTestBase {

    static final ZoneOffset KST = ZoneOffset.ofHours(9);
    static final AtomicInteger DAY = new AtomicInteger(700);

    /** 시험마다 다른 날 오전 10시. */
    static OffsetDateTime slot() {
        LocalDate d = LocalDate.now(KST).plusDays(DAY.incrementAndGet());
        return d.atTime(10, 0).atOffset(KST);
    }

    private Map<String, Object> body(String room, OffsetDateTime s, OffsetDateTime e) {
        return new HashMap<>(Map.of("roomId", room, "startsAt", s.toString(), "endsAt", e.toString(), "title", "회의"));
    }

    private MockHttpServletResponse reserve(String emp, String room, OffsetDateTime s, OffsetDateTime e)
            throws Exception {
        return post("/room-reservations", emp, body(room, s, e));
    }

    @Test
    void reserveConflictAvailabilityAndUndo() throws Exception {
        String a = members("rnd").get(0);
        String b = members("rnd").get(1);
        OffsetDateTime s = slot();
        MockHttpServletResponse r = reserve(a, "room-a", s, s.plusHours(1));
        assertThat(r.getStatus()).as(r.getContentAsString()).isEqualTo(201);
        JsonNode res = json(r);
        assertThat(res.path("resource").path("status").asText()).isEqualTo("confirmed");
        assertThat(res.path("undoable").asBoolean()).isTrue();
        // 겹치는 시간(일부만 겹쳐도)
        assertThat(problem(reserve(b, "room-a", s.plusMinutes(30), s.plusMinutes(90)))).isEqualTo("room-conflict");
        // 붙어 있는 시간은 됨
        assertThat(reserve(b, "room-a", s.plusHours(1), s.plusHours(2)).getStatus()).isEqualTo(201);
        // 빈 회의실
        JsonNode avail = json(get("/rooms/availability", b, "startsAt", s.toString(), "endsAt",
                s.plusHours(1).toString())).path("items");
        assertThat(avail.findValuesAsText("id")).doesNotContain("room-a").contains("room-b");
        assertThat(json(get("/rooms/availability", b, "startsAt", s.toString(), "endsAt", s.plusHours(1).toString(),
                "minCapacity", "10")).path("items").findValuesAsText("id")).containsOnly("room-d");
        assertThat(get("/rooms/availability", b, "startsAt", s.toString(), "endsAt", s.toString()).getStatus())
                .isEqualTo(422);
        // 남의 예약은 제목이 가려짐
        JsonNode all = json(get("/room-reservations", b, "mine", "false", "roomId", "room-a", "date",
                s.toLocalDate().toString())).path("items");
        assertThat(all.size()).isEqualTo(2);
        assertThat(all.get(0).path("title").asText()).isEqualTo("예약됨");
        assertThat(all.get(1).path("title").asText()).isEqualTo("회의");
        assertThat(json(get("/room-reservations", a)).path("items").findValuesAsText("id"))
                .contains(res.path("resource").path("id").asText());
        // 되돌리기 = 취소, 그 뒤 다른 사람이 예약 가능
        assertThat(post("/actions/" + res.path("actionId").asText() + "/undo", a, Map.of()).getStatus()).isEqualTo(201);
        assertThat(reserve(b, "room-a", s, s.plusHours(1)).getStatus()).isEqualTo(201);
    }

    @Test
    void slotRules() throws Exception {
        String a = members("rnd").get(2);
        OffsetDateTime s = slot();
        List<OffsetDateTime[]> bad = List.of(
                new OffsetDateTime[] {s.plusMinutes(10), s.plusHours(1)},
                new OffsetDateTime[] {s, s.plusHours(4).plusMinutes(30)},
                new OffsetDateTime[] {s, s.minusHours(1)},
                new OffsetDateTime[] {s.withHour(23), s.withHour(23).plusHours(1).plusMinutes(30)},
                new OffsetDateTime[] {s.plusSeconds(1), s.plusHours(1)},
                new OffsetDateTime[] {OffsetDateTime.now(KST).withMinute(0).withSecond(0).withNano(0).minusHours(2),
                        OffsetDateTime.now(KST).withMinute(0).withSecond(0).withNano(0).minusHours(1)});
        for (OffsetDateTime[] x : bad) {
            MockHttpServletResponse r = reserve(a, "room-b", x[0], x[1]);
            assertThat(r.getStatus()).as(x[0] + " ~ " + x[1]).isEqualTo(422);
            assertThat(problem(r)).isEqualTo("validation");
        }
        // 4시간 정확히, 다른 시간대 표기(UTC)도 같은 시각이면 됨
        assertThat(reserve(a, "room-b", s, s.plusHours(4)).getStatus()).isEqualTo(201);
        OffsetDateTime utc = s.plusDays(1).withOffsetSameInstant(ZoneOffset.UTC);
        assertThat(reserve(a, "room-b", utc, utc.plusMinutes(30)).getStatus()).isEqualTo(201);
        assertThat(problem(reserve(a, "room-zz", s.plusDays(2), s.plusDays(2).plusHours(1)))).isEqualTo("validation");
        Map<String, Object> noOffset = body("room-b", s, s.plusHours(1));
        noOffset.put("startsAt", "2027-01-01T10:00:00");
        assertThat(problem(post("/room-reservations", a, noOffset))).isEqualTo("validation");
    }

    @Test
    void concurrentSameSlotOneWins() throws Exception {
        OffsetDateTime s = slot();
        List<String> people = members("production-control").subList(0, 4);
        ExecutorService pool = Executors.newFixedThreadPool(people.size());
        CountDownLatch go = new CountDownLatch(1);
        List<Future<MockHttpServletResponse>> fs = new ArrayList<>();
        for (String who : people) {
            Callable<MockHttpServletResponse> c = () -> {
                go.await();
                return reserve(who, "room-c", s, s.plusHours(2));
            };
            fs.add(pool.submit(c));
        }
        go.countDown();
        List<String> outcomes = new ArrayList<>();
        for (Future<MockHttpServletResponse> f : fs) {
            MockHttpServletResponse r = f.get();
            outcomes.add(r.getStatus() == 201 ? "ok" : problem(r));
        }
        pool.shutdown();
        assertThat(outcomes).containsOnlyOnce("ok");
        assertThat(outcomes).filteredOn(o -> !o.equals("ok")).containsOnly("room-conflict");
    }

    @Test
    void cancelAndUndoCancel() throws Exception {
        String a = members("quality").get(0);
        String b = members("quality").get(1);
        OffsetDateTime s = slot();
        String id = json(reserve(a, "room-d", s, s.plusHours(1))).path("resource").path("id").asText();
        assertThat(problem(post("/room-reservations/" + id + "/cancel", b, Map.of()))).isEqualTo("forbidden");
        assertThat(problem(post("/room-reservations/nope/cancel", a, Map.of()))).isEqualTo("not-found");
        JsonNode cancel = json(post("/room-reservations/" + id + "/cancel", a, Map.of()));
        assertThat(cancel.path("resource").path("status").asText()).isEqualTo("cancelled");
        assertThat(problem(post("/room-reservations/" + id + "/cancel", a, Map.of()))).isEqualTo("invalid-state");
        // 비어 있으면 취소를 되돌려 되살림
        assertThat(post("/actions/" + cancel.path("actionId").asText() + "/undo", a, Map.of()).getStatus())
                .isEqualTo(201);
        // 다시 취소하고, 그 자리에 다른 예약이 들어오면 되돌리기 충돌
        JsonNode cancel2 = json(post("/room-reservations/" + id + "/cancel", a, Map.of()));
        assertThat(reserve(b, "room-d", s, s.plusHours(1)).getStatus()).isEqualTo(201);
        assertThat(problem(post("/actions/" + cancel2.path("actionId").asText() + "/undo", a, Map.of())))
                .isEqualTo("undo-conflict");
    }

    @Test
    void roomsFromPack() throws Exception {
        String a = members("quality").get(2);
        assertThat(json(get("/rooms", a)).path("items").size()).isEqualTo(pack.rooms().size());
        assertThat(json(get("/rooms", a, "minCapacity", "8")).path("items").findValuesAsText("id"))
                .containsExactly("room-c", "room-d");
    }
}
