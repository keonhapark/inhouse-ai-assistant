package io.inhouse.erp.room;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;

@Entity
@Table(name = "room_reservation")
public class RoomReservation {

    public static final String CONFIRMED = "confirmed";
    public static final String CANCELLED = "cancelled";

    @Id
    private String id;
    @Column(name = "room_id")
    private String roomId;
    @Column(name = "reserved_by")
    private String reservedBy;
    @Column(name = "starts_at")
    private OffsetDateTime startsAt;
    @Column(name = "ends_at")
    private OffsetDateTime endsAt;
    private String title;
    private Integer attendees;
    private String status;

    protected RoomReservation() {}

    RoomReservation(String id, String roomId, String reservedBy, OffsetDateTime startsAt, OffsetDateTime endsAt,
                    String title, Integer attendees) {
        this.id = id;
        this.roomId = roomId;
        this.reservedBy = reservedBy;
        this.startsAt = startsAt;
        this.endsAt = endsAt;
        this.title = title;
        this.attendees = attendees;
        this.status = CONFIRMED;
    }

    void setStatus(String status) {
        this.status = status;
    }

    public boolean isConfirmed() { return CONFIRMED.equals(status); }

    public String getId() { return id; }
    public String getRoomId() { return roomId; }
    public String getReservedBy() { return reservedBy; }
    public OffsetDateTime getStartsAt() { return startsAt; }
    public OffsetDateTime getEndsAt() { return endsAt; }
    public String getTitle() { return title; }
    public Integer getAttendees() { return attendees; }
    public String getStatus() { return status; }
}
