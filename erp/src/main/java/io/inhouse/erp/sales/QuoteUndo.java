package io.inhouse.erp.sales;

import io.inhouse.erp.write.Action;
import io.inhouse.erp.write.UndoHandler;
import io.inhouse.erp.write.WriteOutcome;
import org.springframework.stereotype.Component;

/** 견적 초안 되돌리기(취소). 발행은 되돌리지 않습니다. */
@Component
class QuoteUndo implements UndoHandler {

    private final QuoteService quotes;

    QuoteUndo(QuoteService quotes) {
        this.quotes = quotes;
    }

    @Override
    public String operation() {
        return "createQuote";
    }

    @Override
    public WriteOutcome undo(Action original) {
        return quotes.undoCreate(original.getResourceId());
    }
}
