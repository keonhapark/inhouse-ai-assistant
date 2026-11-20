package io.inhouse.erp.room;

import io.inhouse.erp.write.Action;
import io.inhouse.erp.write.UndoHandler;
import io.inhouse.erp.write.WriteOutcome;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** 회의실 예약 되돌리기(취소)와 취소 되돌리기(되살리기). */
@Configuration
class RoomUndo {

    @Bean
    UndoHandler undoReserve(RoomService rooms) {
        return handler("createRoomReservation", a -> rooms.undoReserve(a.getResourceId()));
    }

    @Bean
    UndoHandler undoCancel(RoomService rooms) {
        return handler("cancelRoomReservation", a -> rooms.undoCancel(a.getResourceId()));
    }

    private static UndoHandler handler(String operation, java.util.function.Function<Action, WriteOutcome> fn) {
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
