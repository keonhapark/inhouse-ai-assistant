package io.inhouse.erp.approval;

import io.inhouse.erp.write.Action;
import io.inhouse.erp.write.UndoHandler;
import io.inhouse.erp.write.WriteOutcome;
import org.springframework.stereotype.Component;

@Component
class CreateDocumentUndo implements UndoHandler {

    private final ApprovalService approvals;

    CreateDocumentUndo(ApprovalService approvals) {
        this.approvals = approvals;
    }

    @Override
    public String operation() {
        return "createApprovalDocument";
    }

    @Override
    public WriteOutcome undo(Action original) {
        return approvals.undoCreate(original.getResourceId());
    }
}
