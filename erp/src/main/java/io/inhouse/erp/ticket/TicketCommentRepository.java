package io.inhouse.erp.ticket;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface TicketCommentRepository extends JpaRepository<TicketComment, String> {

    List<TicketComment> findByTicketIdOrderByCreatedAtAscIdAsc(String ticketId);

    long countByTicketId(String ticketId);
}
