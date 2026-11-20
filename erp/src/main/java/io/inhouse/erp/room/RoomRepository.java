package io.inhouse.erp.room;

import jakarta.persistence.LockModeType;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface RoomRepository extends JpaRepository<Room, String> {

    /**
     * 같은 회의실에 대한 예약·되살리기를 줄 세웁니다. 잠금 없이 동시에 INSERT하면 배제 제약이 서로를 기다리다
     * 교착(40P01)으로 끝나 409 대신 500이 날 수 있습니다.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select r from Room r where r.id = :id")
    Optional<Room> lockById(@Param("id") String id);
}
