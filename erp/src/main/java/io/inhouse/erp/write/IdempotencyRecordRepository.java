package io.inhouse.erp.write;

import java.time.OffsetDateTime;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface IdempotencyRecordRepository extends JpaRepository<IdempotencyRecord, IdempotencyRecord.Key> {

    /** 보관이 지난 같은 키를 지웁니다. 지울 것이 없어도(동시 요청이 먼저 지워도) 예외가 나지 않습니다. */
    @Modifying(flushAutomatically = true)
    @Query("delete from IdempotencyRecord r where r.ownerId = :owner and r.idemKey = :key and r.createdAt < :before")
    int deleteExpired(@Param("owner") String owner, @Param("key") String key, @Param("before") OffsetDateTime before);

    @Modifying
    @Query("delete from IdempotencyRecord r where r.createdAt < :before")
    int deleteOlderThan(@Param("before") OffsetDateTime before);
}
