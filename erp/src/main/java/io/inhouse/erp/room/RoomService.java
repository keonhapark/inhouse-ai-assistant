package io.inhouse.erp.room;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Ids;
import io.inhouse.erp.pack.Pack;
import io.inhouse.erp.write.Change;
import io.inhouse.erp.write.WriteOutcome;
import java.time.Clock;
import java.time.Duration;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 회의실 예약. 30분 단위(정각·30분), 같은 날 안, 최대 4시간, 지난 시각은 안 됩니다(시각은 팩 시간대 기준).
 * 겹침은 먼저 조회로 거절하고, 조회를 함께 지난 동시 요청은 DB 배제 제약(room_reservation_no_overlap)이 막습니다.
 */
@Service
public class RoomService {

    public record ReservationView(String id, String roomId, String reservedBy, OffsetDateTime startsAt,
                                  OffsetDateTime endsAt, String title, Integer attendees, String status) {}

    public record ReserveRequest(String roomId, OffsetDateTime startsAt, OffsetDateTime endsAt, String title,
                                 Integer attendees) {}

    static final Duration MAX_LENGTH = Duration.ofHours(4);
    static final String HIDDEN_TITLE = "예약됨";
    private static final DateTimeFormatter WHEN = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm");
    private static final DateTimeFormatter HOUR = DateTimeFormatter.ofPattern("HH:mm");

    private final RoomRepository rooms;
    private final RoomReservationRepository reservations;
    private final ObjectMapper mapper;
    private final ZoneId zone;
    private final Clock clock;

    public RoomService(RoomRepository rooms, RoomReservationRepository reservations, ObjectMapper mapper, Pack pack,
                       Clock clock) {
        this.rooms = rooms;
        this.reservations = reservations;
        this.mapper = mapper;
        this.zone = pack.timezone();
        this.clock = clock;
    }

    // ---------- 예약·취소 ----------

    public WriteOutcome reserve(ErpPrincipal p, ReserveRequest req) {
        Room room = rooms.findById(req.roomId() == null ? "" : req.roomId())
                .orElseThrow(() -> ApiException.validation("roomId", "unknown"));
        validateSlot(req.startsAt(), req.endsAt());
        if (reservations.overlaps(room.getId(), req.startsAt(), req.endsAt(), "")) {
            throw conflict(room);
        }
        RoomReservation r = new RoomReservation(Ids.next("rsv"), room.getId(), p.employeeId(), req.startsAt(),
                req.endsAt(), req.title(), req.attendees());
        try {
            reservations.saveAndFlush(r);
        } catch (DataIntegrityViolationException e) {
            throw conflict(room);
        }
        ReservationView view = view(r, true);
        return WriteOutcome.of(room.getName() + "을 " + span(r) + "에 예약합니다",
                new Change("create", "room_reservation", r.getId(), null, json(view)), true, view, r.getId());
    }

    /** 예약자 본인만 취소합니다. */
    public WriteOutcome cancel(ErpPrincipal p, String reservationId) {
        RoomReservation r = reservations.lockById(reservationId)
                .orElseThrow(() -> ApiException.notFound("예약이 없습니다"));
        if (!r.getReservedBy().equals(p.employeeId())) {
            throw ApiException.forbidden("예약자 본인만 취소합니다");
        }
        if (!r.isConfirmed()) {
            throw new ApiException(409, "invalid-state", "이미 취소된 예약입니다");
        }
        JsonNode before = json(view(r, true));
        r.setStatus(RoomReservation.CANCELLED);
        ReservationView after = view(reservations.saveAndFlush(r), true);
        return WriteOutcome.of(roomName(r) + " 예약(" + WHEN.format(local(r.getStartsAt())) + ")을 취소합니다",
                new Change("update", "room_reservation", r.getId(), before, json(after)), true, after, r.getId());
    }

    /** 예약 되돌리기: 시작 전이면 취소와 같습니다. */
    public WriteOutcome undoReserve(String reservationId) {
        RoomReservation r = reservations.lockById(reservationId).orElseThrow();
        if (!r.isConfirmed()) {
            throw new ApiException(409, "undo-conflict", "이미 취소된 예약입니다");
        }
        if (!r.getStartsAt().isAfter(OffsetDateTime.now(clock))) {
            throw new ApiException(409, "undo-conflict", "예약 시작 시각이 지났습니다");
        }
        JsonNode before = json(view(r, true));
        r.setStatus(RoomReservation.CANCELLED);
        ReservationView after = view(reservations.saveAndFlush(r), true);
        return WriteOutcome.of("회의실 예약을 되돌렸습니다(취소)",
                new Change("update", "room_reservation", r.getId(), before, json(after)), false, after, r.getId());
    }

    /** 취소 되돌리기: 같은 시간대가 아직 비어 있고 시작 전이면 예약을 되살립니다. */
    public WriteOutcome undoCancel(String reservationId) {
        RoomReservation r = reservations.lockById(reservationId).orElseThrow();
        if (r.isConfirmed()) {
            throw new ApiException(409, "undo-conflict", "예약이 취소 상태가 아닙니다");
        }
        if (!r.getStartsAt().isAfter(OffsetDateTime.now(clock))) {
            throw new ApiException(409, "undo-conflict", "예약 시작 시각이 지났습니다");
        }
        if (reservations.overlaps(r.getRoomId(), r.getStartsAt(), r.getEndsAt(), r.getId())) {
            throw new ApiException(409, "undo-conflict", "그 시간에 다른 예약이 들어왔습니다");
        }
        JsonNode before = json(view(r, true));
        r.setStatus(RoomReservation.CONFIRMED);
        try {
            reservations.saveAndFlush(r);
        } catch (DataIntegrityViolationException e) {
            throw new ApiException(409, "undo-conflict", "그 시간에 다른 예약이 들어왔습니다");
        }
        ReservationView after = view(r, true);
        return WriteOutcome.of("예약 취소를 되돌렸습니다",
                new Change("update", "room_reservation", r.getId(), before, json(after)), false, after, r.getId());
    }

    private void validateSlot(OffsetDateTime s, OffsetDateTime e) {
        ZonedDateTime sk = local(s);
        ZonedDateTime ek = local(e);
        String bad = null;
        if (!s.isBefore(e)) {
            bad = "시작이 끝보다 앞이어야 합니다";
        } else if (sk.getMinute() % 30 != 0 || ek.getMinute() % 30 != 0 || sk.getSecond() != 0
                || ek.getSecond() != 0 || sk.getNano() != 0 || ek.getNano() != 0) {
            bad = "30분 단위로 예약합니다";
        } else if (!sk.toLocalDate().equals(ek.toLocalDate())) {
            bad = "같은 날 안에서 예약합니다";
        } else if (Duration.between(s, e).compareTo(MAX_LENGTH) > 0) {
            bad = "최대 4시간입니다";
        } else if (!s.isAfter(OffsetDateTime.now(clock))) {
            bad = "지난 시각은 예약할 수 없습니다";
        }
        if (bad != null) {
            throw new ApiException(422, "validation", bad, List.of(new ApiException.FieldError("startsAt", bad)));
        }
    }

    // ---------- 조회 ----------

    @Transactional(readOnly = true)
    public List<Room> rooms(Integer minCapacity) {
        return rooms.findAll().stream().filter(r -> minCapacity == null || r.getCapacity() >= minCapacity)
                .sorted(java.util.Comparator.comparing(Room::getId)).toList();
    }

    @Transactional(readOnly = true)
    public List<Room> available(OffsetDateTime s, OffsetDateTime e, Integer minCapacity) {
        if (!s.isBefore(e)) {
            throw ApiException.validation("endsAt", "시작이 끝보다 앞이어야 합니다");
        }
        Set<String> busy = new HashSet<>(reservations.busyRooms(s, e));
        return rooms(minCapacity).stream().filter(r -> !busy.contains(r.getId())).toList();
    }

    /** 남의 예약은 제목을 가립니다. */
    @Transactional(readOnly = true)
    public List<ReservationView> list(String employeeId, boolean mine, String roomId, LocalDate date) {
        OffsetDateTime from = date == null ? null : date.atStartOfDay(zone).toOffsetDateTime();
        OffsetDateTime to = date == null ? null : date.plusDays(1).atStartOfDay(zone).toOffsetDateTime();
        return reservations.search(employeeId, mine, roomId, from, to).stream()
                .map(r -> view(r, r.getReservedBy().equals(employeeId))).toList();
    }

    private ReservationView view(RoomReservation r, boolean showTitle) {
        return new ReservationView(r.getId(), r.getRoomId(), r.getReservedBy(), local(r.getStartsAt()).toOffsetDateTime(),
                local(r.getEndsAt()).toOffsetDateTime(), showTitle ? r.getTitle() : HIDDEN_TITLE, r.getAttendees(),
                r.getStatus());
    }

    private ApiException conflict(Room room) {
        return new ApiException(409, "room-conflict", room.getName() + "에 겹치는 예약이 있습니다");
    }

    private String span(RoomReservation r) {
        return WHEN.format(local(r.getStartsAt())) + "~" + HOUR.format(local(r.getEndsAt()));
    }

    private String roomName(RoomReservation r) {
        return rooms.findById(r.getRoomId()).map(Room::getName).orElse(r.getRoomId());
    }

    private ZonedDateTime local(OffsetDateTime t) {
        return t.atZoneSameInstant(zone);
    }

    private JsonNode json(Object o) {
        return mapper.valueToTree(o);
    }
}
