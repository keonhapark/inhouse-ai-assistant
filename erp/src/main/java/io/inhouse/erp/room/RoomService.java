package io.inhouse.erp.room;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Ids;
import io.inhouse.erp.common.Ko;
import io.inhouse.erp.pack.Pack;
import io.inhouse.erp.write.Change;
import io.inhouse.erp.write.WriteOutcome;
import java.time.Clock;
import java.time.Duration;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 회의실 예약. 30분 단위(정각·30분), 같은 날 안, 최대 4시간, 지난 시각은 안 됩니다(시각은 팩 시간대 기준).
 * 같은 회의실 예약은 회의실 행을 잠가 줄 세운 뒤 겹침을 조회로 거절합니다. DB 배제 제약(room_reservation_no_overlap)은
 * 마지막 보장입니다.
 */
@Service
public class RoomService {

    public record ReservationView(String id, String roomId, String reservedBy, OffsetDateTime startsAt,
                                  OffsetDateTime endsAt, String title, Integer attendees, String status) {}

    public record ReserveRequest(String roomId, OffsetDateTime startsAt, OffsetDateTime endsAt, String title,
                                 Integer attendees) {}

    static final Duration MAX_LENGTH = Duration.ofHours(4);
    static final String HIDDEN_TITLE = "예약됨";

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
        Room room = rooms.lockById(req.roomId() == null ? "" : req.roomId())
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
        return WriteOutcome.of(Ko.eul(room.getName()) + " " + span(r) + "에 예약합니다",
                new Change("create", "room_reservation", r.getId(), null, json(view)), true, view, r.getId());
    }

    /** 예약자 본인만 취소합니다. */
    public WriteOutcome cancel(ErpPrincipal p, String reservationId) {
        RoomReservation r = reservations.lockById(reservationId)
                .orElseThrow(() -> ApiException.notFound("예약이 없습니다"));
        if (!r.getReservedBy().equals(p.employeeId())) {
            throw ApiException.forbidden("예약한 사람만 취소할 수 있습니다.");
        }
        if (!r.isConfirmed()) {
            throw new ApiException(409, "invalid-state", "이미 취소한 예약입니다.");
        }
        JsonNode before = json(view(r, true));
        r.setStatus(RoomReservation.CANCELLED);
        ReservationView after = view(reservations.saveAndFlush(r), true);
        return WriteOutcome.of(roomName(r) + " 예약(" + Ko.when(local(r.getStartsAt())) + ")을 취소합니다",
                new Change("update", "room_reservation", r.getId(), before, json(after)), true, after, r.getId());
    }

    /** 예약 되돌리기: 시작 전이면 취소와 같습니다. */
    public WriteOutcome undoReserve(String reservationId) {
        RoomReservation r = reservations.lockById(reservationId).orElseThrow();
        if (!r.isConfirmed()) {
            throw new ApiException(409, "undo-conflict", "이미 취소한 예약입니다.");
        }
        if (!r.getStartsAt().isAfter(OffsetDateTime.now(clock))) {
            throw new ApiException(409, "undo-conflict", "이미 시작한 예약이라 실행 취소할 수 없습니다.");
        }
        JsonNode before = json(view(r, true));
        r.setStatus(RoomReservation.CANCELLED);
        ReservationView after = view(reservations.saveAndFlush(r), true);
        return WriteOutcome.of("회의실 예약을 취소했습니다",
                new Change("update", "room_reservation", r.getId(), before, json(after)), false, after, r.getId());
    }

    /** 취소 되돌리기: 같은 시간대가 아직 비어 있고 시작 전이면 예약을 되살립니다. */
    public WriteOutcome undoCancel(String reservationId) {
        RoomReservation r = reservations.lockById(reservationId).orElseThrow();
        if (r.isConfirmed()) {
            throw new ApiException(409, "undo-conflict", "이미 다시 잡힌 예약입니다.");
        }
        if (!r.getStartsAt().isAfter(OffsetDateTime.now(clock))) {
            throw new ApiException(409, "undo-conflict", "이미 시작 시각이 지난 예약이라 되살릴 수 없습니다.");
        }
        rooms.lockById(r.getRoomId());
        if (reservations.overlaps(r.getRoomId(), r.getStartsAt(), r.getEndsAt(), r.getId())) {
            throw new ApiException(409, "undo-conflict", "그사이 같은 시간에 다른 예약이 잡혀 되살릴 수 없습니다. 다른 시간으로 새로 예약하세요.");
        }
        JsonNode before = json(view(r, true));
        r.setStatus(RoomReservation.CONFIRMED);
        try {
            reservations.saveAndFlush(r);
        } catch (DataIntegrityViolationException e) {
            throw new ApiException(409, "undo-conflict", "그사이 같은 시간에 다른 예약이 잡혀 되살릴 수 없습니다. 다른 시간으로 새로 예약하세요.");
        }
        ReservationView after = view(r, true);
        return WriteOutcome.of("취소한 예약을 되살렸습니다",
                new Change("update", "room_reservation", r.getId(), before, json(after)), false, after, r.getId());
    }

    private void validateSlot(OffsetDateTime s, OffsetDateTime e) {
        ZonedDateTime sk = local(s);
        ZonedDateTime ek = local(e);
        String bad = null;
        if (!s.isBefore(e)) {
            bad = "끝나는 시각은 시작 시각보다 늦어야 합니다.";
        } else if (sk.getMinute() % 30 != 0 || ek.getMinute() % 30 != 0 || sk.getSecond() != 0
                || ek.getSecond() != 0 || sk.getNano() != 0 || ek.getNano() != 0) {
            bad = "30분 단위로만 예약할 수 있습니다.";
        } else if (!sk.toLocalDate().equals(ek.toLocalDate())) {
            bad = "하루 안에서만 예약할 수 있습니다.";
        } else if (Duration.between(s, e).compareTo(MAX_LENGTH) > 0) {
            bad = "한 번에 4시간까지 예약할 수 있습니다.";
        } else if (!s.isAfter(OffsetDateTime.now(clock))) {
            bad = "지난 시각은 예약할 수 없습니다. 지금 이후 시각을 고르세요.";
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
            throw ApiException.invalid("endsAt", "끝나는 시각은 시작 시각보다 늦어야 합니다.");
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
        return new ApiException(409, "room-conflict", Ko.eun(room.getName()) + " 그 시간에 이미 예약돼 있습니다. 다른 시간을 고르세요.");
    }

    private String span(RoomReservation r) {
        return Ko.span(local(r.getStartsAt()), local(r.getEndsAt()));
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
