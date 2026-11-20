package io.inhouse.erp.ticket;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.auth.RequiredScope;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Bodies;
import io.inhouse.erp.common.OperationId;
import io.inhouse.erp.org.OrgViews.Items;
import io.inhouse.erp.write.WriteExecutor;
import io.inhouse.erp.write.WriteRequest;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Set;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class TicketController {

    private final TicketService tickets;
    private final WriteExecutor writes;

    public TicketController(TicketService tickets, WriteExecutor writes) {
        this.tickets = tickets;
        this.writes = writes;
    }

    @GetMapping("/tickets")
    @OperationId("listTickets")
    @RequiredScope("ticket:read")
    public Items<TicketService.TicketView> list(@AuthenticationPrincipal ErpPrincipal p,
                                                @RequestParam(defaultValue = "mine") String box,
                                                @RequestParam(required = false) String status,
                                                @RequestParam(defaultValue = "20") int limit) {
        return new Items<>(tickets.list(p.employeeId(), box, status, limit));
    }

    @GetMapping("/tickets/{ticketId}")
    @OperationId("getTicket")
    @RequiredScope("ticket:read")
    public TicketService.TicketDetail get(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String ticketId) {
        return tickets.detail(p.employeeId(), ticketId);
    }

    @PostMapping("/tickets")
    @OperationId("createTicket")
    @RequiredScope("ticket:write")
    public ResponseEntity<Object> create(@AuthenticationPrincipal ErpPrincipal p,
                                         @RequestParam(defaultValue = "false") boolean dryRun,
                                         @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                         @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        Bodies.check(body, Set.of("category", "title", "description", "priority"),
                Set.of("category", "title", "description"));
        TicketService.CreateRequest req = new TicketService.CreateRequest(
                oneOf(body, "category", Ticket.CATEGORIES, null), oneOf(body, "priority", Ticket.PRIORITIES, "normal"),
                nonBlank(body, "title", 100), nonBlank(body, "description", 2000));
        WriteRequest w = WriteRequest.of(p, "createTicket", "ticket", http.getRequestURI(), body, dryRun, key);
        return writes.run(w, () -> tickets.create(p, req));
    }

    @PostMapping("/tickets/{ticketId}/comments")
    @OperationId("addTicketComment")
    @RequiredScope("ticket:write")
    public ResponseEntity<Object> comment(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String ticketId,
                                          @RequestParam(defaultValue = "false") boolean dryRun,
                                          @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                          @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        Bodies.check(body, Set.of("body"), Set.of("body"));
        String text = nonBlank(body, "body", 2000);
        WriteRequest w = WriteRequest.of(p, "addTicketComment", "ticket_comment", http.getRequestURI(), body, dryRun,
                key);
        return writes.run(w, () -> tickets.comment(p, ticketId, text));
    }

    @PostMapping("/tickets/{ticketId}/status")
    @OperationId("changeTicketStatus")
    @RequiredScope("ticket:manage")
    public ResponseEntity<Object> status(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String ticketId,
                                         @RequestParam(defaultValue = "false") boolean dryRun,
                                         @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                         @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        Bodies.check(body, Set.of("status", "version"), Set.of("status", "version"));
        String status = oneOf(body, "status", Ticket.STATUSES, null);
        int version = Bodies.integer(body, "version");
        if (version < 0) {
            throw ApiException.validation("version", "integer >= 0 required");
        }
        WriteRequest w = WriteRequest.of(p, "changeTicketStatus", "ticket_status_change", http.getRequestURI(), body,
                dryRun, key);
        return writes.run(w, () -> tickets.changeStatus(p, ticketId, status, version));
    }

    private static String nonBlank(JsonNode body, String field, int maxLength) {
        String v = Bodies.text(body, field, maxLength);
        if (v == null || v.isBlank()) {
            throw ApiException.validation(field, "1~" + maxLength + "자");
        }
        return v;
    }

    private static String oneOf(JsonNode body, String field, Set<String> allowed, String fallback) {
        String v = Bodies.text(body, field, 32);
        if (v == null) {
            v = fallback;
        }
        if (v == null || !allowed.contains(v)) {
            throw ApiException.validation(field, "unknown value");
        }
        return v;
    }
}
