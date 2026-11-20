package io.inhouse.erp.ticket;

import io.inhouse.erp.write.Action;
import io.inhouse.erp.write.UndoHandler;
import io.inhouse.erp.write.WriteOutcome;
import java.util.function.Function;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** IT 티켓 작성·댓글·상태 변경 되돌리기. */
@Configuration
class TicketUndo {

    @Bean
    UndoHandler undoCreateTicket(TicketService tickets) {
        return handler("createTicket", a -> tickets.undoCreate(a.getResourceId()));
    }

    @Bean
    UndoHandler undoTicketComment(TicketService tickets) {
        return handler("addTicketComment", a -> tickets.undoComment(a.getResourceId()));
    }

    @Bean
    UndoHandler undoTicketStatus(TicketService tickets) {
        return handler("changeTicketStatus", a -> tickets.undoStatus(a.getResourceId(), a.getActorId()));
    }

    private static UndoHandler handler(String operation, Function<Action, WriteOutcome> fn) {
        return new UndoHandler() {
            @Override
            public String operation() {
                return operation;
            }

            @Override
            public WriteOutcome undo(Action original) {
                return fn.apply(original);
            }
        };
    }
}
