package io.inhouse.erp.room;

import jakarta.persistence.LockModeType;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface RoomReservationRepository extends JpaRepository<RoomReservation, String> {

    @Query("""
            select count(r) > 0 from RoomReservation r
            where r.roomId = :roomId and r.status = 'confirmed' and r.id <> :ignore
              and r.startsAt < :endsAt and :startsAt < r.endsAt""")
    boolean overlaps(@Param("roomId") String roomId, @Param("startsAt") OffsetDateTime startsAt,
                     @Param("endsAt") OffsetDateTime endsAt, @Param("ignore") String ignoreId);

    @Query("""
            select distinct r.roomId from RoomReservation r
            where r.status = 'confirmed' and r.startsAt < :endsAt and :startsAt < r.endsAt""")
    List<String> busyRooms(@Param("startsAt") OffsetDateTime startsAt, @Param("endsAt") OffsetDateTime endsAt);

    @Query("""
            select r from RoomReservation r
            where (:mine = false or r.reservedBy = :emp)
              and (:roomId is null or r.roomId = :roomId)
              and (cast(:from as timestamp) is null or (r.startsAt >= :from and r.startsAt < :to))
            order by r.startsAt""")
    List<RoomReservation> search(@Param("emp") String employeeId, @Param("mine") boolean mine,
                                 @Param("roomId") String roomId, @Param("from") OffsetDateTime from,
                                 @Param("to") OffsetDateTime to);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select r from RoomReservation r where r.id = :id")
    Optional<RoomReservation> lockById(@Param("id") String id);
}
