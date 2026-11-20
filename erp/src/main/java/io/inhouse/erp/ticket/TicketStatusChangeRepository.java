package io.inhouse.erp.ticket;

import org.springframework.data.jpa.repository.JpaRepository;

public interface TicketStatusChangeRepository extends JpaRepository<TicketStatusChange, String> {}
