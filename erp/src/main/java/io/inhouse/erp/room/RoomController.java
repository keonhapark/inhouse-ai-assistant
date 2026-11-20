package io.inhouse.erp.room;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.auth.RequiredScope;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Bodies;
import io.inhouse.erp.org.OrgViews.Items;
import io.inhouse.erp.room.RoomService.ReservationView;
import io.inhouse.erp.write.WriteExecutor;
import io.inhouse.erp.write.WriteRequest;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.Set;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class RoomController {

    private static final String RESOURCE = "room_reservation";

    private final RoomService rooms;
    private final WriteExecutor writes;

    public RoomController(RoomService rooms, WriteExecutor writes) {
        this.rooms = rooms;
        this.writes = writes;
    }

    @GetMapping("/rooms")
    @RequiredScope("room:read")
    public Items<Room> list(@RequestParam(required = false) Integer minCapacity) {
        return new Items<>(rooms.rooms(positive(minCapacity)));
    }

    @GetMapping("/rooms/availability")
    @RequiredScope("room:read")
    public Items<Room> availability(@RequestParam String startsAt, @RequestParam String endsAt,
                                    @RequestParam(required = false) Integer minCapacity) {
        return new Items<>(rooms.available(time("startsAt", startsAt), time("endsAt", endsAt), positive(minCapacity)));
    }

    @GetMapping("/room-reservations")
    @RequiredScope("room:read")
    public Items<ReservationView> reservations(@AuthenticationPrincipal ErpPrincipal p,
                                               @RequestParam(defaultValue = "true") boolean mine,
                                               @RequestParam(required = false) String roomId,
                                               @RequestParam(required = false) String date) {
        LocalDate day;
        try {
            day = date == null ? null : LocalDate.parse(date);
        } catch (DateTimeParseException e) {
            throw ApiException.validation("date", "YYYY-MM-DD");
        }
        return new Items<>(rooms.list(p.employeeId(), mine, roomId, day));
    }

    @PostMapping("/room-reservations")
    @RequiredScope("room:write")
    public ResponseEntity<Object> reserve(@AuthenticationPrincipal ErpPrincipal p,
                                          @RequestParam(defaultValue = "false") boolean dryRun,
                                          @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                          @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        Bodies.check(body, Set.of("roomId", "startsAt", "endsAt", "title", "attendees"),
                Set.of("roomId", "startsAt", "endsAt", "title"));
        Integer attendees = null;
        if (body.hasNonNull("attendees")) {
            if (!body.get("attendees").isIntegralNumber() || body.get("attendees").asInt() < 1) {
                throw ApiException.validation("attendees", "integer >= 1 required");
            }
            attendees = body.get("attendees").asInt();
        }
        RoomService.ReserveRequest req = new RoomService.ReserveRequest(Bodies.text(body, "roomId", 64),
                time("startsAt", Bodies.text(body, "startsAt", 64)), time("endsAt", Bodies.text(body, "endsAt", 64)),
                Bodies.text(body, "title", 100), attendees);
        WriteRequest w = WriteRequest.of(p, "createRoomReservation", RESOURCE, http.getRequestURI(), body, dryRun, key);
        return writes.run(w, () -> rooms.reserve(p, req));
    }

    @PostMapping("/room-reservations/{reservationId}/cancel")
    @RequiredScope("room:write")
    public ResponseEntity<Object> cancel(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String reservationId,
                                         @RequestParam(defaultValue = "false") boolean dryRun,
                                         @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                         @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        WriteRequest w = WriteRequest.of(p, "cancelRoomReservation", RESOURCE, http.getRequestURI(), body, dryRun, key);
        return writes.run(w, () -> rooms.cancel(p, reservationId));
    }

    private static Integer positive(Integer n) {
        if (n != null && n < 1) {
            throw ApiException.validation("minCapacity", "integer >= 1 required");
        }
        return n;
    }

    private static OffsetDateTime time(String field, String value) {
        try {
            return OffsetDateTime.parse(value);
        } catch (DateTimeParseException | NullPointerException e) {
            throw ApiException.validation(field, "RFC 3339(오프셋 포함)");
        }
    }
}
