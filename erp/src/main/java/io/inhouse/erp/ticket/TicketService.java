package io.inhouse.erp.ticket;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Ids;
import io.inhouse.erp.org.OrgService;
import io.inhouse.erp.pack.Pack;
import io.inhouse.erp.write.Change;
import io.inhouse.erp.write.WriteOutcome;
import java.time.Clock;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;
import org.springframework.data.domain.Limit;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * IT 티켓(계약 erp.yaml tickets). 올린 사람과 티켓 담당 역할(팩 erp_roles.ticket_handler)만 봅니다.
 * 상태 변경은 담당만 하고, 같은 티켓의 쓰기는 티켓 행을 잠가 줄 세웁니다.
 */
@Service
public class TicketService {

    public record TicketView(String id, String requesterId, String category, String priority, String title,
                             String description, String status, int version, int commentCount,
                             OffsetDateTime createdAt, OffsetDateTime updatedAt) {}

    public record CommentView(String id, String ticketId, String authorId, String body, OffsetDateTime createdAt) {}

    public record TicketDetail(String id, String requesterId, String category, String priority, String title,
                               String description, String status, int version, int commentCount,
                               OffsetDateTime createdAt, OffsetDateTime updatedAt, List<CommentView> comments) {}

    public record CreateRequest(String category, String priority, String title, String description) {}

    private final TicketRepository tickets;
    private final TicketCommentRepository comments;
    private final TicketStatusChangeRepository changes;
    private final OrgService org;
    private final ObjectMapper mapper;
    private final ZoneId zone;
    private final Clock clock;

    public TicketService(TicketRepository tickets, TicketCommentRepository comments,
                         TicketStatusChangeRepository changes, OrgService org, ObjectMapper mapper, Pack pack,
                         Clock clock) {
        this.tickets = tickets;
        this.comments = comments;
        this.changes = changes;
        this.org = org;
        this.mapper = mapper;
        this.zone = pack.timezone();
        this.clock = clock;
    }

    // ---------- 조회 ----------

    /** box=mine은 내가 올린 것, box=all은 담당만(그 밖에는 403). 최근에 바뀐 순입니다. */
    @Transactional(readOnly = true)
    public List<TicketView> list(String employeeId, String box, String status, int limit) {
        if (!"mine".equals(box) && !"all".equals(box)) {
            throw ApiException.validation("box", "mine, all 중 하나");
        }
        if (status != null && !Ticket.STATUSES.contains(status)) {
            throw ApiException.validation("status", "unknown");
        }
        if ("all".equals(box) && !org.isTicketHandler(employeeId)) {
            throw ApiException.forbidden("티켓 담당만 전체를 봅니다");
        }
        String requester = "mine".equals(box) ? employeeId : null;
        return tickets.search(requester, status, Limit.of(Math.max(1, Math.min(limit, 100)))).stream()
                .map(this::view).toList();
    }

    @Transactional(readOnly = true)
    public TicketDetail detail(String employeeId, String ticketId) {
        Ticket t = visible(employeeId, tickets.findById(ticketId).orElse(null));
        List<CommentView> cs = comments.findByTicketIdOrderByCreatedAtAscIdAsc(t.getId()).stream()
                .map(this::view).toList();
        return new TicketDetail(t.getId(), t.getRequesterId(), t.getCategory(), t.getPriority(), t.getTitle(),
                t.getDescription(), t.getStatus(), t.getVersion(), cs.size(), at(t.getCreatedAt()),
                at(t.getUpdatedAt()), cs);
    }

    // ---------- 쓰기 ----------

    public WriteOutcome create(ErpPrincipal p, CreateRequest req) {
        OffsetDateTime now = OffsetDateTime.now(clock);
        Ticket t = tickets.saveAndFlush(new Ticket(Ids.next("tkt"), p.employeeId(), req.category(), req.priority(),
                req.title(), req.description(), "open", now));
        TicketView after = view(t);
        return WriteOutcome.of("IT 티켓 '" + t.getTitle() + "'을 올립니다",
                new Change("create", "ticket", t.getId(), null, json(after)), true, after, t.getId());
    }

    /** 작성 되돌리기: 아직 open이고 댓글이 없으면 cancelled로 둡니다. */
    public WriteOutcome undoCreate(String ticketId) {
        Ticket t = tickets.lockById(ticketId).orElseThrow();
        if (!"open".equals(t.getStatus()) || comments.countByTicketId(ticketId) > 0) {
            throw new ApiException(409, "undo-conflict", "그사이 댓글이 달렸거나 처리가 시작됐습니다");
        }
        return statusOutcome(t, "cancelled", "IT 티켓 작성을 되돌렸습니다(취소)", false);
    }

    /** 올린 사람과 담당만 씁니다(그 밖에는 404). closed·cancelled면 409입니다. */
    public WriteOutcome comment(ErpPrincipal p, String ticketId, String body) {
        Ticket t = visible(p.employeeId(), tickets.lockById(ticketId).orElse(null));
        if (t.isFinished()) {
            throw new ApiException(409, "invalid-state", t.getStatus() + " 티켓에는 댓글을 달 수 없습니다");
        }
        OffsetDateTime now = OffsetDateTime.now(clock);
        TicketComment c = comments.saveAndFlush(new TicketComment(Ids.next("tcm"), t.getId(), p.employeeId(), body,
                now));
        t.touch(now);
        tickets.saveAndFlush(t);
        CommentView after = view(c);
        return WriteOutcome.of("IT 티켓 '" + t.getTitle() + "'에 댓글을 답니다",
                new Change("create", "ticket_comment", c.getId(), null, json(after)), true, after, c.getId());
    }

    /** 댓글 되돌리기: 티켓이 closed·cancelled가 아니면 지웁니다. */
    public WriteOutcome undoComment(String commentId) {
        TicketComment c = comments.findById(commentId).orElseThrow();
        Ticket t = tickets.lockById(c.getTicketId()).orElseThrow();
        if (t.isFinished()) {
            throw new ApiException(409, "undo-conflict", "티켓이 " + t.getStatus() + "입니다");
        }
        CommentView before = view(c);
        comments.delete(c);
        comments.flush();
        return WriteOutcome.of("IT 티켓 댓글을 지웠습니다",
                new Change("delete", "ticket_comment", c.getId(), json(before), null), false, before, c.getId());
    }

    /**
     * 담당만 바꿉니다(볼 수 있지만 담당이 아니면 403, 볼 수 없으면 404). version이 다르면 409 version-conflict,
     * 바꿀 수 없는 상태면 409 invalid-state입니다. 행동은 상태 변경 이력 행을 가리킵니다(되돌리기 기준).
     */
    public WriteOutcome changeStatus(ErpPrincipal p, String ticketId, String status, int version) {
        Ticket t = visible(p.employeeId(), tickets.lockById(ticketId).orElse(null));
        if (!org.isTicketHandler(p.employeeId())) {
            throw ApiException.forbidden("티켓 담당만 상태를 바꿉니다");
        }
        if (version != t.getVersion()) {
            throw new ApiException(409, "version-conflict", "그사이 티켓이 바뀌었습니다");
        }
        if (!Ticket.TRANSITIONS.getOrDefault(t.getStatus(), java.util.Set.of()).contains(status)) {
            throw new ApiException(409, "invalid-state", t.getStatus() + "에서 " + status + "로 바꿀 수 없습니다");
        }
        String from = t.getStatus();
        WriteOutcome out = statusOutcome(t, status, "IT 티켓 '" + t.getTitle() + "'을 " + status + "로 바꿉니다", true);
        TicketStatusChange log = changes.saveAndFlush(new TicketStatusChange(Ids.next("tsc"), t.getId(), from, status,
                t.getVersion(), p.employeeId(), t.getUpdatedAt()));
        return new WriteOutcome(out.summary(), out.changes(), true, out.resource(), log.getId(), null, null);
    }

    /** 상태 변경 되돌리기: 그사이 상태가 다시 바뀌지 않았으면 이전 상태로 돌립니다. */
    public WriteOutcome undoStatus(String changeId) {
        TicketStatusChange c = changes.findById(changeId).orElseThrow();
        Ticket t = tickets.lockById(c.getTicketId()).orElseThrow();
        if (t.getVersion() != c.getVersionAfter()) {
            throw new ApiException(409, "undo-conflict", "그사이 상태가 다시 바뀌었습니다");
        }
        return statusOutcome(t, c.getFromStatus(), "IT 티켓 상태 변경을 되돌렸습니다", false);
    }

    private WriteOutcome statusOutcome(Ticket t, String status, String summary, boolean undoable) {
        JsonNode before = json(view(t));
        t.changeStatus(status, OffsetDateTime.now(clock));
        TicketView after = view(tickets.saveAndFlush(t));
        return WriteOutcome.of(summary, new Change("update", "ticket", t.getId(), before, json(after)), undoable,
                after, t.getId());
    }

    private Ticket visible(String employeeId, Ticket t) {
        if (t == null || !(t.getRequesterId().equals(employeeId) || org.isTicketHandler(employeeId))) {
            throw ApiException.notFound("티켓이 없습니다");
        }
        return t;
    }

    private TicketView view(Ticket t) {
        return new TicketView(t.getId(), t.getRequesterId(), t.getCategory(), t.getPriority(), t.getTitle(),
                t.getDescription(), t.getStatus(), t.getVersion(), t.getCommentCount(), at(t.getCreatedAt()),
                at(t.getUpdatedAt()));
    }

    private CommentView view(TicketComment c) {
        return new CommentView(c.getId(), c.getTicketId(), c.getAuthorId(), c.getBody(), at(c.getCreatedAt()));
    }

    private OffsetDateTime at(OffsetDateTime t) {
        return t.atZoneSameInstant(zone).toOffsetDateTime();
    }

    private JsonNode json(Object o) {
        return mapper.valueToTree(o);
    }
}
