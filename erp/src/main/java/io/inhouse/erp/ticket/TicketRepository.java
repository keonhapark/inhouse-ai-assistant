package io.inhouse.erp.ticket;

import jakarta.persistence.LockModeType;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Limit;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface TicketRepository extends JpaRepository<Ticket, String> {

    @Query("""
            select t from Ticket t
            where (:requester is null or t.requesterId = :requester)
              and (:status is null or t.status = :status)
            order by t.updatedAt desc, t.id desc""")
    List<Ticket> search(@Param("requester") String requesterId, @Param("status") String status, Limit limit);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select t from Ticket t where t.id = :id")
    Optional<Ticket> lockById(@Param("id") String id);
}
