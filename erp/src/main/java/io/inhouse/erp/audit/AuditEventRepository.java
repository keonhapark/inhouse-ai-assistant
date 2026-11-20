package io.inhouse.erp.audit;

import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.data.domain.Limit;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface AuditEventRepository extends JpaRepository<AuditEventEntity, Long> {

    /** 조건에 맞는 것 중 최근 것부터. 호출하는 쪽에서 시간 순으로 뒤집습니다. */
    @Query("""
            select a from AuditEventEntity a
            where (:actorId is null or a.actorId = :actorId)
              and (:actionId is null or a.actionId = :actionId)
              and (cast(:since as timestamp) is null or a.occurredAt >= :since)
            order by a.seq desc""")
    List<AuditEventEntity> latest(@Param("actorId") String actorId, @Param("actionId") String actionId,
                                  @Param("since") OffsetDateTime since, Limit limit);
}
