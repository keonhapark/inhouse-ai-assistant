package io.inhouse.erp.ticket;

import io.inhouse.erp.pack.Pack;
import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.stereotype.Component;

/**
 * 팩 fixtures/tickets.json의 티켓을 넣습니다. 티켓은 쓰면서 바뀌므로 없는 것만 넣습니다(연차 잔여와 같음).
 * 고정 댓글 ID는 tcm_&lt;티켓 번호&gt;_&lt;순번&gt;입니다(가짜 erp와 같음).
 */
@Component
public class TicketFixtures {

    private final TicketRepository tickets;
    private final TicketCommentRepository comments;

    public TicketFixtures(TicketRepository tickets, TicketCommentRepository comments) {
        this.tickets = tickets;
        this.comments = comments;
    }

    /** 새로 넣은 티켓 수를 돌려줍니다. */
    public int seed(List<Pack.TicketDef> defs) {
        int added = 0;
        for (Pack.TicketDef d : defs) {
            if (tickets.existsById(d.id())) {
                continue;
            }
            Ticket t = new Ticket(d.id(), d.requesterId(), d.category(), d.priority(), d.title(), d.description(),
                    d.status(), d.createdAt());
            int i = 0;
            OffsetDateTime last = d.createdAt();
            for (Pack.CommentDef c : d.comments()) {
                last = c.createdAt().isAfter(last) ? c.createdAt() : last;
            }
            t.touch(last);
            tickets.saveAndFlush(t);
            for (Pack.CommentDef c : d.comments()) {
                comments.save(new TicketComment("tcm_" + d.id().replaceFirst("^tkt_", "") + "_" + (++i), d.id(),
                        c.authorId(), c.body(), c.createdAt()));
            }
            added++;
        }
        comments.flush();
        return added;
    }
}
